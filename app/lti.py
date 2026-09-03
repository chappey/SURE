import json
import sys
import threading
import time
import typing as t
from html import escape

from fastapi.responses import RedirectResponse, HTMLResponse

from urllib.parse import urlencode

from app import config
from pylti1p3.request import Request
from pylti1p3.cookie import CookieService
from pylti1p3.session import SessionService
from pylti1p3.redirect import Redirect
from pylti1p3.oidc_login import OIDCLogin
from pylti1p3.message_launch import MessageLaunch
from pylti1p3.launch_data_storage.base import LaunchDataStorage


class InMemoryDataStorage(LaunchDataStorage[t.Any]):
    """Process-local TTL store for OIDC states, nonces, and state params.

    Hardening over a plain dict:
    - entries expire (``exp`` seconds; default ``default_expiration``), so an
      unauthenticated flood of ``/login`` requests cannot grow memory forever;
    - the store is bounded — when ``max_entries`` is exceeded the oldest
      entries are evicted first;
    - expired/nonce values are only readable once within their TTL window,
      preserving pylti1p3's nonce-replay protection.

    Still process-local by design (multi-worker deployments need Redis or
    similar behind this same interface).
    """

    _DEFAULT_EXPIRATION = 5 * 60  # matches the OIDC state-cookie lifetime
    _MAX_ENTRIES = 10_000

    def __init__(self, *, default_expiration: int = _DEFAULT_EXPIRATION,
                 max_entries: int = _MAX_ENTRIES):
        self._cache: dict[str, tuple[t.Any, float | None]] = {}
        self._lock = threading.Lock()
        self._default_expiration = int(default_expiration)
        self._max_entries = int(max_entries)

    def get_session_cookie_name(self) -> None:
        return None

    def set_session_id(self, session_id: str) -> None:
        pass

    def _prepare_key(self, key: str | None) -> str | None:
        # LaunchDataStorage prefixes keys with session_id when set; we never
        # set one, so keep keys global but namespace them per purpose upstream.
        return key

    def _purge_expired_locked(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._cache.items() if exp is not None and exp <= now]
        for k in expired:
            del self._cache[k]

    def get_value(self, key: str) -> t.Any:
        prepared_key = self._prepare_key(key)
        now = time.time()
        with self._lock:
            entry = self._cache.get(prepared_key)
            if entry is None:
                return None
            value, exp = entry
            if exp is not None and exp <= now:
                del self._cache[prepared_key]
                return None
            return value

    def set_value(self, key: str, value: t.Any, exp: t.Optional[int] = None) -> None:
        prepared_key = self._prepare_key(key)
        try:
            ttl = float(exp) if exp is not None else float(self._default_expiration)
        except (TypeError, ValueError):
            ttl = float(self._default_expiration)
        expires_at = time.time() + ttl
        with self._lock:
            self._cache[prepared_key] = (value, expires_at)
            if len(self._cache) > self._max_entries:
                self._purge_expired_locked(time.time())
            if len(self._cache) > self._max_entries:
                # Evict oldest-by-expiry until under budget.
                overflow = len(self._cache) - self._max_entries
                oldest = sorted(
                    self._cache.items(), key=lambda kv: kv[1][1] or 0
                )[:overflow]
                for k, _ in oldest:
                    del self._cache[k]

    def check_value(self, key: str) -> bool:
        return self.get_value(key) is not None

    def can_set_keys_expiration(self) -> bool:
        return True

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
        # Match the session-cookie policy in app/config.py: on plain-HTTP dev,
        # Chromium rejects SameSite=None cookies that are not Secure, which drops
        # the OIDC state/nonce cookies and breaks /launch ("State not found").
        # Canvas and the tool share one host in local dev (same-site), so Lax is
        # sent on the launch POST. HTTPS keeps None+Secure for cross-site iframe POST.
        if config.LOCAL_HTTP_LTI:
            secure = False
            same_site = "lax"
        else:
            secure = self._request.is_secure()
            same_site = "none"
        for key, cookie_data in self._cookie_data_to_set.items():
            response.set_cookie(
                key=key,
                value=str(cookie_data["value"]),
                max_age=cookie_data["exp"],
                secure=secure,
                path="/",
                httponly=True,
                samesite=same_site,
            )


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
        # json.dumps safely embeds the URL as a JS string literal (quotes,
        # backslashes, and closing tags are escaped).
        location_json = json.dumps(self._location)
        html_content = (
            f'<script type="text/javascript">window.location={location_json};</script>'
        )
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


class LocalHttpCookiesAllowedCheckPage:
    """Cookie probe for HTTP dev Canvas — pylti1p3's default test gives false positives in iframes."""

    def __init__(
        self,
        params: t.Mapping[str, str],
        main_text: str,
        click_text: str,
        loading_text: str,
    ) -> None:
        self._params = params
        self._main_text = main_text
        self._click_text = click_text
        self._loading_text = loading_text

    def get_html(self) -> str:
        js_block = """\
        var urlParams = %s;
        var htmlEntities = {
            "&lt;": "<",
            "&gt;": ">",
            "&amp;": "&",
            "&quot;": '"',
            "&#x27;": "'"
        };

        function unescapeHtmlEntities(str) {
            for (var htmlCode in htmlEntities) {
                str = str.replace(new RegExp(htmlCode, "g"), htmlEntities[htmlCode]);
            }
            return str;
        }

        function getUpdatedUrl() {
            var newSearchParams = [];
            for (var key in urlParams) {
                if (window.location.search.indexOf(key + '=') === -1) {
                    newSearchParams.push(key + '=' + encodeURIComponent(unescapeHtmlEntities(urlParams[key])));
                }
            }
            var searchParamsStr = newSearchParams.join('&');
            if (window.location.search !== '') {
                searchParamsStr = window.location.search + '&' + searchParamsStr;
            } else {
                searchParamsStr = '?' + searchParamsStr;
            }
            return window.location.protocol + '//' + window.location.hostname +
                (window.location.port ? (":" + window.location.port) : "") +
                window.location.pathname + searchParamsStr;
        }

        function displayLoadingBlock() {
            document.getElementById("lti1p3-loading-msg").style.display = "block";
        }

        function displayWarningBlock() {
            document.getElementById("lti1p3-warning-msg").style.display = "block";
            var newTabLink = document.getElementById("lti1p3-new-tab-link");
            var contentUrl = getUpdatedUrl();
            newTabLink.onclick = function() {
                window.open(contentUrl , '_blank');
                newTabLink.parentNode.removeChild(newTabLink);
            };
        }

        function checkCookiesAllowed() {
            // Cross-port localhost is cross-site; iframe launches cannot complete LTI OIDC.
            if (window.self !== window.top) {
                displayWarningBlock();
                return;
            }
            // Top-level: verify SameSite=None cookies (what LTI actually uses on HTTP dev).
            var cookie = "lti1p3_test_cookie=1; path=/; SameSite=None";
            document.cookie = cookie;
            var res = document.cookie.indexOf("lti1p3_test_cookie") !== -1;
            if (res) {
                document.cookie = "lti1p3_test_cookie=1; expires=Thu, 01-Jan-1970 00:00:01 GMT";
                displayLoadingBlock();
                window.location.href = getUpdatedUrl();
            } else {
                displayWarningBlock();
            }
        }

        document.addEventListener("DOMContentLoaded", checkCookiesAllowed);
        """
        js_block = js_block % json.dumps({k: escape(v, True) for k, v in self._params.items()})

        return f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
        <title></title>
        <meta charset="UTF-8">
        <style type="text/css">
        body {{
        font-family: Geneva, Arial, Helvetica, sans-serif;
        }}
        </style>
        <script type="text/javascript">
        {js_block}
        </script>
        </head>
        <body>
        <div id="lti1p3-loading-msg" style="display: none;">
        {self._loading_text}
        </div>
        <div id="lti1p3-warning-msg" style="display: none;">
        <p><strong>{self._main_text}</strong> <a href="javascript: void(0);" id="lti1p3-new-tab-link">{self._click_text}</a></p>
        </div>
        </body>
        </html>
        """


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

    def get_cookies_allowed_js_check(self) -> str:
        if not config.LOCAL_HTTP_LTI:
            return super().get_cookies_allowed_js_check()

        params_lst = [
            "iss",
            "login_hint",
            "target_link_uri",
            "lti_message_hint",
            "lti_deployment_id",
            "client_id",
        ]
        params_lst.extend(self.get_additional_login_params())
        params: dict[str, str] = {"lti1p3_new_window": "1"}
        for param_key in params_lst:
            param_value = self._get_request_param(param_key)
            if param_value:
                params[param_key] = str(param_value)

        page = LocalHttpCookiesAllowedCheckPage(
            params,
            self._cookies_unavailable_msg_main_text,
            self._cookies_unavailable_msg_click_text,
            self._cookies_check_loading_text,
        )
        return page.get_html()

    def _prepare_redirect_url(self, launch_url: str) -> str:
        """OIDC redirect; for local HTTP, force prompt=login to work around cookie policy differences."""
        from pylti1p3.exception import OIDCException

        launch_url = config.rewrite_tool_url(launch_url)
        if not launch_url:
            raise OIDCException("No launch URL configured")

        if self._launch_data_storage:
            self.set_launch_data_storage(self._launch_data_storage)

        self._registration = self.validate_oidc_login()

        state = "state-" + self._get_uuid()
        self._cookie_service.set_cookie(state, state, 5 * 60)

        nonce = self._generate_nonce()
        self._session_service.save_nonce(nonce)
        if self._state_params:
            self._session_service.save_state_params(state, self._state_params)

        client_id = self._registration.get_client_id()
        assert client_id is not None, "Client id should not be None"
        auth_login_url = self._registration.get_auth_login_url()
        assert auth_login_url is not None, "Auth login url should not be None"
        auth_login_url = config.rewrite_canvas_url(auth_login_url)

        # prompt=none fails on HTTP Canvas when session cookies are SameSite=Strict
        # (cross-port redirect from :8000 → :3000). prompt=login forces re-auth.
        prompt = "login" if config.LOCAL_HTTP_LTI else "none"

        auth_params = {
            "scope": "openid",
            "response_type": "id_token",
            "response_mode": "form_post",
            "prompt": prompt,
            "client_id": client_id,
            "redirect_uri": launch_url,
            "state": state,
            "nonce": nonce,
            "login_hint": self._get_request_param("login_hint"),
        }

        lti_message_hint = self._get_request_param("lti_message_hint")
        if lti_message_hint:
            auth_params["lti_message_hint"] = lti_message_hint

        return auth_login_url + "?" + urlencode(auth_params)


EasyLearnOIDCLogin = FastAPIOIDCLogin


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
