#!/usr/bin/env python3
"""Provision local Canvas test users and enroll them in a course.

Reads CANVAS_API_URL and CANVAS_API_TOKEN from the environment (or .env via app config).

Usage:
  CANVAS_API_TOKEN=... uv run utils/setup_canvas_test_users.py
  CANVAS_API_TOKEN=... uv run utils/setup_canvas_test_users.py --course-id 3 --publish
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

DEFAULT_PASSWORD = "EasyLearn123!"
DEFAULT_USERS = [
    ("teacher1@example.com", "Professor Ada", "TeacherEnrollment"),
    ("teacher2@example.com", "Professor Ben", "TeacherEnrollment"),
    ("student1@example.com", "Student Casey", "StudentEnrollment"),
]


def _api(method: str, path: str, data: dict | None = None) -> tuple[int, dict | str]:
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
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def ensure_user(login: str, name: str, password: str) -> int:
    """Create user or return existing user id."""
    status, body = _api(
        "POST",
        "/api/v1/accounts/1/users",
        {
            "user": {
                "name": name,
                "short_name": name.split()[-1],
                "sortable_name": name,
            },
            "pseudonym": {
                "unique_id": login,
                "password": password,
                "send_confirmation": False,
            },
            "communication_channel": {
                "type": "email",
                "address": login,
                "skip_confirmation": True,
            },
        },
    )
    if status in (200, 201):
        return body["id"] if isinstance(body, dict) else json.loads(body)["id"]

    # User may already exist — look up by login
    status, body = _api("GET", f"/api/v1/accounts/1/users?search_term={login}")
    if status == 200 and isinstance(body, list) and body:
        for user in body:
            if user.get("login_id") == login:
                return int(user["id"])
    raise RuntimeError(f"Could not create or find user {login}: HTTP {status} {body}")


def enroll(course_id: int, user_id: int, enrollment_type: str) -> None:
    status, body = _api(
        "POST",
        f"/api/v1/courses/{course_id}/enrollments",
        {
            "enrollment": {
                "user_id": user_id,
                "type": enrollment_type,
                "enrollment_state": "active",
            }
        },
    )
    if status not in (200, 201):
        raise RuntimeError(f"Enrollment failed for user {user_id}: HTTP {status} {body}")


def publish_course(course_id: int) -> None:
    status, body = _api(
        "PUT",
        f"/api/v1/courses/{course_id}",
        {"offer": True, "published": True, "event": "offer"},
    )
    if status != 200:
        raise RuntimeError(f"Could not publish course {course_id}: HTTP {status} {body}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create local Canvas test users")
    parser.add_argument("--course-id", type=int, default=int(config.CANVAS_COURSE_ID or "3"))
    parser.add_argument("--publish", action="store_true", help="Publish the target course")
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    print(f"Canvas: {config.CANVAS_API_URL}")
    print(f"Course: {args.course_id}")
    print(f"Password for new users: {args.password}\n")

    for login, name, etype in DEFAULT_USERS:
        uid = ensure_user(login, name, args.password)
        enroll(args.course_id, uid, etype)
        role = "teacher" if "Teacher" in etype else "student"
        print(f"  {login} (id={uid}, {role})")

    if args.publish:
        publish_course(args.course_id)
        print(f"\nPublished course {args.course_id}")

    print("\nDone. Log into Canvas with each account and launch EasyLearn from course navigation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
