"""LTI tool configuration singleton."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from pylti1p3.tool_config import ToolConfDict

from app.config import CANVAS_PUBLIC_URL, LTI_CONFIG_PATH

# Canvas platform issuer for OIDC login — sent even when the browser uses a custom domain.
CANVAS_INSTRUCTURE_ISS = "https://canvas.instructure.com"

_KEY_PATH_FIELDS = ("private_key_file", "public_key_file")


def _resolve_key_paths(data: dict) -> None:
    """Resolve ../keys/*.key paths relative to config/ (ToolConfDict has no file context)."""
    base = LTI_CONFIG_PATH.parent.resolve()
    for registrations in data.values():
        if not isinstance(registrations, list):
            continue
        for registration in registrations:
            if not isinstance(registration, dict):
                continue
            for field in _KEY_PATH_FIELDS:
                raw = registration.get(field)
                if not raw or not isinstance(raw, str):
                    continue
                path = Path(raw)
                if not path.is_absolute():
                    registration[field] = str((base / path).resolve())


def _copy_instructure_issuer(data: dict) -> None:
    """Register canvas.instructure.com using the same tool keys as the public Canvas host."""
    if CANVAS_INSTRUCTURE_ISS in data:
        return

    public = CANVAS_PUBLIC_URL.rstrip("/")
    if not public.startswith("https://"):
        return

    source = data.get(public)
    if not source:
        for iss, registrations in data.items():
            if iss.startswith("https://") and iss != CANVAS_INSTRUCTURE_ISS:
                source = registrations
                break
    if source:
        data[CANVAS_INSTRUCTURE_ISS] = copy.deepcopy(source)


def _load_key_files(tool_conf: ToolConfDict, data: dict) -> None:
    """Read PEM files into tool_conf (ToolConfJsonFile does this; ToolConfDict does not)."""
    for iss, iss_conf in data.items():
        entries = iss_conf if isinstance(iss_conf, list) else [iss_conf]
        for registration in entries:
            if not isinstance(registration, dict):
                continue
            client_id = registration.get("client_id")
            private_path = registration.get("private_key_file")
            public_path = registration.get("public_key_file")
            if private_path:
                tool_conf.set_private_key(
                    iss,
                    Path(private_path).read_text(encoding="utf-8"),
                    client_id=client_id,
                )
            if public_path:
                tool_conf.set_public_key(
                    iss,
                    Path(public_path).read_text(encoding="utf-8"),
                    client_id=client_id,
                )


def load_lti_settings() -> dict:
    """Load lti_config.json and ensure the Canvas platform issuer is registered."""
    if not LTI_CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {LTI_CONFIG_PATH}. "
            "Copy config/lti_config.example.json to config/lti_config.json and edit it "
            "with your Canvas issuer, client_id, and deployment_ids."
        )
    data = json.loads(LTI_CONFIG_PATH.read_text(encoding="utf-8"))
    _resolve_key_paths(data)
    _copy_instructure_issuer(data)
    return data


def build_tool_conf() -> ToolConfDict:
    data = load_lti_settings()
    conf = ToolConfDict(data)
    _load_key_files(conf, data)
    return conf


_tool_conf: ToolConfDict | None = None


def get_tool_conf() -> ToolConfDict:
    global _tool_conf
    if _tool_conf is None:
        _tool_conf = build_tool_conf()
    return _tool_conf


def __getattr__(name: str) -> ToolConfDict:
    if name == "tool_conf":
        return get_tool_conf()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
