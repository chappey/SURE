#!/usr/bin/env python3
"""Configure EasyLearn LTI for local Docker dev (canvas.docker + new tab).

Updates the Canvas LTI registration to use:
  - EASYLEARN_PUBLIC_URL (default http://canvas.docker:8000) for tool URLs
  - windowTarget=_blank for course navigation

Requires CANVAS_API_URL, CANVAS_API_TOKEN in .env.
Ensure /etc/hosts maps canvas.docker → 127.0.0.1.

Usage:
  uv run utils/configure_lti_local_dev.py
  uv run utils/configure_lti_local_dev.py --registration-id 2
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402


def _api(method: str, path: str, data: dict | None = None) -> dict:
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
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Canvas API error {exc.code}: {exc.read().decode()}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure LTI for local Docker dev")
    parser.add_argument("--registration-id", type=int, default=2)
    parser.add_argument("--account-id", type=int, default=1)
    args = parser.parse_args()

    tool_base = config.EASYLEARN_PUBLIC_URL.rstrip("/")
    parsed = urlparse(tool_base)
    domain = parsed.netloc or "canvas.docker:8000"
    launch_url = f"{tool_base}/launch"
    login_url = f"{tool_base}/login"
    jwks_url = f"{tool_base}/jwks"

    reg_path = f"/api/v1/accounts/{args.account_id}/lti_registrations/{args.registration_id}?include[]=configuration"
    reg = _api("GET", reg_path)
    cfg = reg["configuration"]

    cfg["domain"] = domain
    cfg["target_link_uri"] = launch_url
    cfg["oidc_initiation_url"] = login_url
    cfg["public_jwk_url"] = jwks_url
    cfg["redirect_uris"] = [launch_url]

    for placement in cfg.get("placements", []):
        if placement.get("placement") == "course_navigation":
            placement["windowTarget"] = "_blank"
            placement["target_link_uri"] = launch_url

    result = _api(
        "PUT",
        f"/api/v1/accounts/{args.account_id}/lti_registrations/{args.registration_id}",
        {
            "name": reg.get("name", "EasyLearn"),
            "description": reg.get("description"),
            "configuration": cfg,
            "comment": "Local Docker dev: canvas.docker URLs + new-tab launch",
        },
    )

    out = result.get("configuration", {})
    print(f"Tool domain:     {out.get('domain')}")
    print(f"Login URL:       {out.get('oidc_initiation_url')}")
    print(f"Launch URL:      {out.get('target_link_uri')}")
    print(f"Redirect URIs:   {out.get('redirect_uris')}")
    for placement in out.get("placements", []):
        if placement.get("placement") == "course_navigation":
            print(f"windowTarget:    {placement.get('windowTarget')!r}")
    print()
    print(f"Canvas (browser): {config.CANVAS_PUBLIC_URL}")
    print(f"EasyLearn:        {config.EASYLEARN_PUBLIC_URL}")
    print("Restart EasyLearn, hard-refresh Canvas, then launch from course nav.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
