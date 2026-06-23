import sys
import typing as t
from fastapi.responses import RedirectResponse, HTMLResponse
from pylti1p3.request import Request
from pylti1p3.cookie import CookieService
from pylti1p3.session import SessionService
from pylti1p3.redirect import Redirect
from pylti1p3.oidc_login import OIDCLogin
from pylti1p3.message_launch import MessageLaunch
from pylti1p3.launch_data_storage.base import LaunchDataStorage

class InMemoryDataStorage(LaunchDataStorage[t.Any]):
    _cache: t.Dict[str, t.Any] = {}

    def get_session_cookie_name(self) -> None:
        return None

    def set_session_id(self, session_id: str) -> None:
        pass

    def get_value(self, key: str) -> t.Any:
        prepared_key = self._prepare_key(key)
        return self._cache.get(prepared_key)

    def set_value(self, key: str, value: t.Any, exp: t.Optional[int] = None) -> None:
        prepared_key = self._prepare_key(key)
        self._cache[prepared_key] = value

    def check_value(self, key: str) -> bool:
        prepared_key = self._prepare_key(key)
        return prepared_key in self._cache

    def can_set_keys_expiration(self) -> bool:
        return False

in_memory_storage = InMemoryDataStorage()

class FastAPIRequest(Request):
    def __init__(self, request, request_data=None):
        super().__init__()
        self._request = request
        self._request_data = request_data or {}

    @property
    def session(self):
        return self._request.session

    def is_secure(self) -> bool:
        if self._request.url.scheme == "https":
            return True
        x_forwarded_proto = self._request.headers.get("x-forwarded-proto")
        if x_forwarded_proto == "https":
            return True
        return False

    def get_param(self, key: str) -> t.Any:
        if key in self._request_data:
            return self._request_data[key]
        val = self._request.query_params.get(key)
        if val is not None:
            return val
        return None

    def get_cookie(self, key: str) -> t.Any:
        return self._request.cookies.get(key)


class FastAPICookieService(CookieService):
    def __init__(self, request: FastAPIRequest):
        self._request = request
        self._cookie_data_to_set = {}

    def _get_key(self, key: str) -> str:
        return self._cookie_prefix + "-" + key

    def get_cookie(self, name: str) -> t.Optional[str]:
        return self._request.get_cookie(self._get_key(name))

    def set_cookie(self, name: str, value: t.Union[str, int], exp: t.Optional[int] = 3600):
        self._cookie_data_to_set[self._get_key(name)] = {"value": value, "exp": exp}

    def update_response(self, response):
        for key, cookie_data in self._cookie_data_to_set.items():
            cookie_kwargs = dict(
                key=key,
                value=str(cookie_data["value"]),
                max_age=cookie_data["exp"],
                secure=True,
                path="/",
                httponly=True,
                samesite="none",
            )
            response.set_cookie(**cookie_kwargs)


class FastAPISessionService(SessionService):
    pass


class FastAPIRedirect(Redirect):
    def __init__(self, location: str, cookie_service: t.Optional[FastAPICookieService] = None):
        super().__init__()
        self._location = location
        self._cookie_service = cookie_service

    def do_redirect(self) -> RedirectResponse:
        response = RedirectResponse(self._location)
        return self._process_response(response)

    def do_js_redirect(self) -> HTMLResponse:
        html_content = f'<script type="text/javascript">window.location="{self._location}";</script>'
        response = HTMLResponse(content=html_content)
        return self._process_response(response)

    def set_redirect_url(self, location: str):
        self._location = location

    def get_redirect_url(self) -> str:
        return self._location

    def _process_response(self, response):
        if self._cookie_service:
            self._cookie_service.update_response(response)
        return response


class FastAPIOIDCLogin(OIDCLogin):
    def __init__(
        self,
        request,
        tool_config,
        session_service=None,
        cookie_service=None,
        launch_data_storage=None,
        request_data=None,
    ):
        self.fastapi_request = FastAPIRequest(request, request_data=request_data)
        cookie_service = (
            cookie_service if cookie_service else FastAPICookieService(self.fastapi_request)
        )
        session_service = (
            session_service if session_service else FastAPISessionService(self.fastapi_request)
        )
        if launch_data_storage is None:
            launch_data_storage = in_memory_storage
        session_service.set_data_storage(launch_data_storage)
        super().__init__(
            self.fastapi_request, tool_config, session_service, cookie_service, launch_data_storage
        )

    def get_redirect(self, url: str) -> FastAPIRedirect:
        return FastAPIRedirect(url, self._cookie_service)

    def get_response(self, html: str) -> HTMLResponse:
        return HTMLResponse(content=html)


class FastAPILTIRequest(MessageLaunch):
    def __init__(
        self,
        request,
        tool_config,
        session_service=None,
        cookie_service=None,
        launch_data_storage=None,
        requests_session=None,
        request_data=None,
    ):
        self.fastapi_request = FastAPIRequest(request, request_data=request_data)
        cookie_service = (
            cookie_service if cookie_service else FastAPICookieService(self.fastapi_request)
        )
        session_service = (
            session_service if session_service else FastAPISessionService(self.fastapi_request)
        )
        if launch_data_storage is None:
            launch_data_storage = in_memory_storage
        session_service.set_data_storage(launch_data_storage)
        super().__init__(
            self.fastapi_request,
            tool_config,
            session_service,
            cookie_service,
            launch_data_storage,
            requests_session,
        )

    def _get_request_param(self, key: str) -> str:
        return self._request.get_param(key)
