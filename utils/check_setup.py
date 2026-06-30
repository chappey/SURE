#!/usr/bin/env python3
"""Preflight "doctor" for EasyLearn.

Validates the local configuration a fresh clone needs before launching:
environment, RSA keys, LTI config issuer match, JWKS generation, Canvas API
connectivity, and the per-professor OAuth mode. Prints a pass/fail checklist.

Usage:
  uv run utils/check_setup.py
  uv run utils/check_setup.py --skip-canvas   # offline checks only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"


class Check:
    """One named check with a status and human-readable detail."""

    def __init__(self, name: str, status: str, detail: str = "") -> None:
        self.name = name
        self.status = status
        self.detail = detail


def check_env() -> Check:
    if not config.CANVAS_API_URL:
        return Check("Environment", FAIL, "CANVAS_API_URL is not set in .env")
    if not config.CANVAS_API_TOKEN:
        return Check(
            "Environment",
            WARN,
            "CANVAS_API_TOKEN is empty (needed for CLI utilities and dev fallback)",
        )
    return Check("Environment", PASS, f"CANVAS_API_URL={config.CANVAS_API_URL}")


def check_keys() -> Check:
    private_key = PROJECT_ROOT / "keys" / "private.key"
    public_key = PROJECT_ROOT / "keys" / "public.key"
    missing = [p.name for p in (private_key, public_key) if not p.is_file()]
    if missing:
        return Check(
            "LTI RSA keys",
            FAIL,
            f"Missing keys/{', keys/'.join(missing)} — run the openssl steps in docs/canvas-setup.md",
        )
    return Check("LTI RSA keys", PASS, "keys/private.key and keys/public.key present")


def check_lti_config() -> Check:
    if not config.LTI_CONFIG_PATH.is_file():
        return Check("LTI config", FAIL, f"Missing {config.LTI_CONFIG_PATH}")

    import json

    try:
        data = json.loads(config.LTI_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("LTI config", FAIL, f"Invalid JSON: {exc}")

    api_host = urlparse(config.CANVAS_API_URL).hostname
    issuer_hosts = {urlparse(issuer).hostname for issuer in data}
    if api_host and api_host not in issuer_hosts:
        return Check(
            "LTI config",
            WARN,
            f"No issuer in lti_config.json matches CANVAS_API_URL host {api_host!r} "
            f"(found: {', '.join(sorted(h for h in issuer_hosts if h))})",
        )
    return Check("LTI config", PASS, f"Issuer present for {api_host}")


def check_jwks() -> Check:
    try:
        from app.lti_config import tool_conf

        jwks = tool_conf.get_jwks()
    except Exception as exc:
        return Check("JWKS generation", FAIL, f"Could not build JWKS: {exc}")
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not keys:
        return Check(
            "JWKS generation",
            FAIL,
            "JWKS is empty — check keys/private.key and keys/public.key paths in lti_config.json",
        )
    return Check("JWKS generation", PASS, f"{len(keys)} key(s) exposed at /jwks")


def check_oauth() -> Check:
    if not config.oauth_enabled():
        return Check(
            "OAuth (per-professor)",
            FAIL,
            "OAuth not configured — run: uv run utils/configure_oauth.py --write-env",
        )
    redirect = config.effective_oauth_redirect_uri()
    scopes = config.CANVAS_OAUTH_SCOPES.strip()
    detail = f"redirect_uri={redirect}"
    if scopes:
        detail += f"; {len(scopes.split())} scope(s) requested"
    return Check("OAuth (per-professor)", PASS, detail)


def check_canvas() -> Check:
    try:
        from app.canvas import get_canvas

        canvas = get_canvas()
        user = canvas.get_current_user()
    except Exception as exc:
        return Check("Canvas API", FAIL, f"Could not reach Canvas: {exc}")
    return Check("Canvas API", PASS, f"Connected as {user.name} (id={user.id})")


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyLearn setup doctor")
    parser.add_argument(
        "--skip-canvas",
        action="store_true",
        help="Skip the live Canvas API connectivity check",
    )
    args = parser.parse_args()

    checks = [
        check_env(),
        check_keys(),
        check_lti_config(),
        check_jwks(),
        check_oauth(),
    ]
    if not args.skip_canvas:
        checks.append(check_canvas())

    print("EasyLearn setup check")
    print("=" * 60)
    for check in checks:
        print(f"[{check.status:>4}] {check.name}")
        if check.detail:
            print(f"        {check.detail}")
    print("=" * 60)

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    if failed:
        print(f"{len(failed)} check(s) failed. See docs/canvas-setup.md.")
        return 1
    if warned:
        print(f"All required checks passed ({len(warned)} warning(s)).")
        return 0
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
