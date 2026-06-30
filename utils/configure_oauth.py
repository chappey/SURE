#!/usr/bin/env python3
"""Create or sync the EasyLearn Canvas OAuth (API) Developer Key.

This is separate from the LTI 1.3 key (configure_lti.py). By default the key
does **not** enforce scopes — professors get API access matching their Canvas role,
and you can leave CANVAS_OAUTH_SCOPES empty in .env.

Requires CANVAS_API_URL and CANVAS_API_TOKEN (admin) in .env.

Usage:
  uv run utils/configure_oauth.py
  uv run utils/configure_oauth.py --write-env          # patch .env with client id/secret
  uv run utils/configure_oauth.py --enforce-scopes     # optional least-privilege scopes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402
from app.canvas_oauth_scopes import EASYLEARN_OAUTH_SCOPES  # noqa: E402

VENDOR_CODE = "easylearn-api"
KEY_NAME = "EasyLearn API"
USER_AGENT = "EasyLearn/0.1.0 (OAuth setup utility)"


def _api(method: str, path: str, data: dict | None = None) -> dict | list:
    base = config.CANVAS_API_URL.rstrip("/")
    token = config.CANVAS_API_TOKEN.strip()
    if not base or not token:
        raise SystemExit("Set CANVAS_API_URL and CANVAS_API_TOKEN in .env")

    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Canvas API error {exc.code}: {exc.read().decode()}") from exc


def _redirect_uri() -> str:
    explicit = config.CANVAS_OAUTH_REDIRECT_URI.strip()
    if explicit:
        return explicit.rstrip("/")
    return f"{config.EASYLEARN_PUBLIC_URL.rstrip('/')}/oauth/callback"


def _list_keys(account_id: int) -> list[dict]:
    keys = _api("GET", f"/api/v1/accounts/{account_id}/developer_keys?per_page=100")
    return keys if isinstance(keys, list) else []


def _find_existing(keys: list[dict]) -> dict | None:
    for key in keys:
        if key.get("vendor_code") == VENDOR_CODE:
            return key
        if key.get("name") == KEY_NAME and not key.get("is_lti_key"):
            return key
    return None


def _create_key(account_id: int, redirect_uri: str, *, enforce_scopes: bool) -> dict:
    payload: dict = {
        "name": KEY_NAME,
        "redirect_uris": [redirect_uri],
        "vendor_code": VENDOR_CODE,
        "visible": True,
        "require_scopes": enforce_scopes,
        "notes": "EasyLearn per-professor OAuth — created by utils/configure_oauth.py",
    }
    if enforce_scopes:
        payload["scopes"] = list(EASYLEARN_OAUTH_SCOPES)
    return _api(
        "POST",
        f"/api/v1/accounts/{account_id}/developer_keys",
        {"developer_key": payload},
    )


def _update_key(key_id: int, redirect_uri: str, *, enforce_scopes: bool) -> dict:
    payload: dict = {
        "name": KEY_NAME,
        "redirect_uris": [redirect_uri],
        "vendor_code": VENDOR_CODE,
        "require_scopes": enforce_scopes,
    }
    if enforce_scopes:
        payload["scopes"] = list(EASYLEARN_OAUTH_SCOPES)
    return _api("PUT", f"/api/v1/developer_keys/{key_id}", {"developer_key": payload})


def _enable_binding(account_id: int, key_id: int) -> dict:
    return _api(
        "POST",
        f"/api/v1/accounts/{account_id}/developer_keys/{key_id}/developer_key_account_bindings",
        {"developer_key_account_binding": {"workflow_state": "on"}},
    )


def _patch_env(client_id: str, client_secret: str | None, redirect_uri: str) -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        raise SystemExit(f"{env_path} not found — copy from .env.example first")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    updates = {
        "CANVAS_CLIENT_ID": client_id,
        "CANVAS_OAUTH_REDIRECT_URI": redirect_uri,
    }
    if client_secret:
        updates["CANVAS_CLIENT_SECRET"] = client_secret

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        matched = False
        for key, value in updates.items():
            if re.match(rf"^\s*#?\s*{re.escape(key)}\s*=", line):
                out.append(f"{key}={value}")
                seen.add(key)
                matched = True
                break
        if not matched:
            out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")

    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"Updated {env_path} with CANVAS_CLIENT_ID and redirect URI.")
    if client_secret:
        print("  (CANVAS_CLIENT_SECRET written — only shown once at key creation.)")
    else:
        print("  (CANVAS_CLIENT_SECRET unchanged — Canvas does not re-send existing secrets.)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/sync the EasyLearn OAuth Developer Key")
    parser.add_argument("--account-id", type=int, default=1)
    parser.add_argument(
        "--enforce-scopes",
        action="store_true",
        help="Enable Enforce Scopes on the key and grant the EasyLearn scope list",
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write CANVAS_CLIENT_ID/SECRET/REDIRECT_URI into .env",
    )
    args = parser.parse_args()

    redirect_uri = _redirect_uri()
    keys = _list_keys(args.account_id)
    existing = _find_existing(keys)
    created = False
    client_secret: str | None = None

    if existing:
        key_id = int(existing["id"])
        print(f"Found existing OAuth key id={key_id} — updating redirect URI and scopes policy.")
        key = _update_key(key_id, redirect_uri, enforce_scopes=args.enforce_scopes)
    else:
        print("Creating new OAuth Developer Key…")
        key = _create_key(args.account_id, redirect_uri, enforce_scopes=args.enforce_scopes)
        key_id = int(key["id"])
        client_secret = key.get("api_key")
        created = True

    binding = _enable_binding(args.account_id, key_id)
    binding_state = binding.get("workflow_state") if isinstance(binding, dict) else "?"

    client_id = str(key.get("id", key_id))
    print()
    print(f"Key name:       {KEY_NAME}")
    print(f"Client ID:      {client_id}")
    print(f"Redirect URI:   {redirect_uri}")
    print(f"Enforce scopes: {args.enforce_scopes}")
    print(f"Account binding:{binding_state!r} (must be 'on')")
    if created and client_secret:
        print(f"Client secret:  {client_secret}")
        print("\nSave the client secret now — Canvas will not show it again.")
    elif not created:
        print("Client secret:  (unchanged — use existing value in .env)")

    if args.enforce_scopes:
        print(f"\nAlso set in .env:\nCANVAS_OAUTH_SCOPES={' '.join(EASYLEARN_OAUTH_SCOPES)}")
    else:
        print("\nScopes: not enforced on the key — leave CANVAS_OAUTH_SCOPES empty in .env.")

    if args.write_env:
        _patch_env(client_id, client_secret if created else None, redirect_uri)

    print("\nRestart EasyLearn, then launch from Canvas as a teacher to authorize.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
