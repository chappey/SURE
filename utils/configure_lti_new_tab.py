#!/usr/bin/env python3
"""Set EasyLearn LTI course_navigation to open in a new tab (windowTarget=_blank).

Required for localhost dev where Canvas (:3000) and EasyLearn (:8000) are cross-site.

Usage:
  uv run utils/configure_lti_new_tab.py
  uv run utils/configure_lti_new_tab.py --registration-id 2
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

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
    parser = argparse.ArgumentParser(description="Configure LTI new-tab launch")
    parser.add_argument("--registration-id", type=int, default=2)
    parser.add_argument("--account-id", type=int, default=1)
    args = parser.parse_args()

    reg_path = f"/api/v1/accounts/{args.account_id}/lti_registrations/{args.registration_id}?include[]=configuration"
    reg = _api("GET", reg_path)
    cfg = reg["configuration"]
    updated_placement = False
    for placement in cfg.get("placements", []):
        if placement.get("placement") == "course_navigation":
            placement["windowTarget"] = "_blank"
            updated_placement = True

    if not updated_placement:
        raise SystemExit("No course_navigation placement found on registration")

    result = _api(
        "PUT",
        f"/api/v1/accounts/{args.account_id}/lti_registrations/{args.registration_id}",
        {
            "name": reg.get("name", "EasyLearn"),
            "description": reg.get("description"),
            "configuration": cfg,
            "comment": "Open EasyLearn in new tab for cross-origin cookie compatibility",
        },
    )

    for placement in result.get("configuration", {}).get("placements", []):
        if placement.get("placement") == "course_navigation":
            print(
                f"Updated registration {args.registration_id}: "
                f"windowTarget={placement.get('windowTarget')!r}"
            )
    print("Click EasyLearn in the course sidebar — it should open in a new tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
