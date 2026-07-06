#!/usr/bin/env python3
"""Sync the EasyLearn LTI registration in Canvas to match local config.

By default this updates the Canvas LTI registration to use EASYLEARN_PUBLIC_URL
for the tool URLs (login/launch/jwks/redirect) and sets the course-navigation
placement to open in a new tab (windowTarget=_blank) — required for local dev
where Canvas and EasyLearn are cross-site (see docs/lti-and-oauth.md).

Requires CANVAS_API_URL and CANVAS_API_TOKEN in .env. For common local dev
with Canvas in Docker using the `canvas.docker` hostname, ensure /etc/hosts
maps it, or set CANVAS_PUBLIC_URL / EASYLEARN_PUBLIC_URL appropriately.

Usage:
  uv run utils/configure_lti.py                     # full URL + new-tab sync
  uv run utils/configure_lti.py --new-tab-only      # only set windowTarget=_blank
  uv run utils/configure_lti.py --registration-id 2 --account-id 1
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
            "User-Agent": "EasyLearn/0.1.0 (LTI setup utility)",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Canvas API error {exc.code}: {exc.read().decode()}") from exc


def _configure_course_navigation(cfg: dict, launch_url: str | None) -> bool:
    """Set course_navigation placement defaults. Returns True if a placement matched."""
    updated = False
    for placement in cfg.get("placements", []):
        if placement.get("placement") == "course_navigation":
            placement["windowTarget"] = "_blank"
            placement["visibility"] = "admins"
            if launch_url:
                placement["target_link_uri"] = launch_url
            updated = True
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure the EasyLearn LTI registration")
    parser.add_argument("--registration-id", type=int, default=2)
    parser.add_argument("--account-id", type=int, default=1)
    parser.add_argument(
        "--new-tab-only",
        action="store_true",
        help="Only set the course-navigation placement to open in a new tab",
    )
    args = parser.parse_args()

    reg_path = (
        f"/api/v1/accounts/{args.account_id}/lti_registrations/"
        f"{args.registration_id}?include[]=configuration"
    )
    reg = _api("GET", reg_path)
    cfg = reg["configuration"]

    tool_base = config.EASYLEARN_PUBLIC_URL.rstrip("/")
    launch_url = f"{tool_base}/launch"

    if args.new_tab_only:
        comment = "Open EasyLearn in a new tab for cross-origin cookie compatibility"
        if not _configure_course_navigation(cfg, launch_url=None):
            raise SystemExit("No course_navigation placement found on registration")
    else:
        comment = "Local dev: sync tool URLs to EASYLEARN_PUBLIC_URL + new-tab launch"
        parsed = urlparse(tool_base)
        cfg["domain"] = parsed.netloc or parsed.hostname or ""
        cfg["target_link_uri"] = launch_url
        cfg["oidc_initiation_url"] = f"{tool_base}/login"
        cfg["public_jwk_url"] = f"{tool_base}/jwks"
        cfg["redirect_uris"] = [launch_url]
        _configure_course_navigation(cfg, launch_url=launch_url)

    result = _api(
        "PUT",
        f"/api/v1/accounts/{args.account_id}/lti_registrations/{args.registration_id}",
        {
            "name": reg.get("name", "EasyLearn"),
            "description": reg.get("description"),
            "configuration": cfg,
            "comment": comment,
        },
    )

    out = result.get("configuration", {})
    if not args.new_tab_only:
        print(f"Tool domain:   {out.get('domain')}")
        print(f"Login URL:     {out.get('oidc_initiation_url')}")
        print(f"Launch URL:    {out.get('target_link_uri')}")
        print(f"Redirect URIs: {out.get('redirect_uris')}")
    for placement in out.get("placements", []):
        if placement.get("placement") == "course_navigation":
            print(f"windowTarget:  {placement.get('windowTarget')!r}")
            print(f"visibility:    {placement.get('visibility')!r}")
    print()
    print(f"Canvas (browser): {config.CANVAS_PUBLIC_URL}")
    print(f"EasyLearn:        {config.EASYLEARN_PUBLIC_URL}")
    print("Restart EasyLearn, hard-refresh Canvas, then launch from course nav.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
