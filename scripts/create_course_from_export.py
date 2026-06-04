#!/usr/bin/env python3
"""Create a Canvas course from an offline export (attachments only)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402, F401 — loads PROJECT_ROOT/.env
from config import PROJECT_ROOT

from course_export import (  # noqa: E402
    iter_attachments,
    load_course_data,
    resolve_export_root,
)
from canvas_client import get_canvas  # noqa: E402

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Canvas course from offline export (PDF/PPTX attachments)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned modules and files without calling the API",
    )
    parser.add_argument(
        "--course-id",
        type=int,
        default=None,
        help="Use an existing course instead of creating a new one",
    )
    parser.add_argument(
        "--skip-empty-modules",
        action="store_true",
        help="Do not create modules that have no attachments",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return parser.parse_args()


def upload_file(course, path: Path) -> int:
    """Upload a file to the course and return its Canvas file id."""
    ok, response = course.upload(str(path))
    if not ok:
        raise RuntimeError(f"Upload failed for {path.name}: {response}")
    file_id = response.get("id")
    if not file_id:
        raise RuntimeError(f"No file id in upload response for {path.name}: {response}")
    return int(file_id)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    export_dir = os.environ.get(
        "COURSE_EXPORT_DIR",
        "Spring-2026-COMPUTER-SCIENCE-PRINCIPLES-CS-10051-600--2026-May-27_17-59-33-518",
    )
    export_root = resolve_export_root(PROJECT_ROOT, export_dir)
    data = load_course_data(export_root)
    attachments = iter_attachments(data, export_root)

    by_module: dict[str, list[tuple[dict, Path]]] = {}
    for mod_name, item, path in attachments:
        by_module.setdefault(mod_name, []).append((item, path))

    modules = data.get("modules", [])
    if args.dry_run:
        print(f"Export: {export_root}")
        print(f"Course title: {data.get('title')}")
        print(f"Modules in export: {len(modules)}")
        print(f"Attachments to upload: {len(attachments)}")
        for i, mod in enumerate(modules, start=1):
            name = mod.get("name", "")
            files = by_module.get(name, [])
            if args.skip_empty_modules and not files:
                print(f"  [{i}] {name} (skip — no attachments)")
                continue
            print(f"  [{i}] {name} ({len(files)} file(s))")
            for item, path in files:
                print(f"        - {item.get('title')} ({path.name})")
        return 0

    canvas = get_canvas()
    account_id = int(os.environ.get("CANVAS_ACCOUNT_ID", "1"))

    if args.course_id:
        course = canvas.get_course(args.course_id)
        log.info("Using existing course id=%s: %s", course.id, course.name)
    else:
        account = canvas.get_account(account_id)
        course = account.create_course(
            course={
                "name": data.get("title", "Imported Course"),
                "course_code": "CS-10051-600",
                "license": "private",
            }
        )
        log.info("Created course id=%s: %s", course.id, course.name)

    uploaded = 0
    failed = 0
    modules_created = 0

    for position, mod in enumerate(modules, start=1):
        name = mod.get("name", "")
        files = by_module.get(name, [])
        if args.skip_empty_modules and not files:
            log.info("Skipping empty module: %s", name)
            continue

        canvas_module = course.create_module({"name": name, "position": position})
        modules_created += 1
        log.info("Module [%s]: %s", position, name)

        if not files:
            continue

        for item, path in files:
            title = item.get("title", path.name)
            try:
                file_id = upload_file(course, path)
                canvas_module.create_module_item(
                    {
                        "type": "File",
                        "content_id": file_id,
                        "title": title,
                        "indent": item.get("indent", 0),
                    }
                )
                uploaded += 1
                log.info("  Uploaded: %s", title)
            except Exception as exc:
                failed += 1
                log.error("  Failed %s: %s", title, exc)

    print()
    print(f"Course URL: {os.environ['CANVAS_API_URL']}/courses/{course.id}")
    print(f"Modules created: {modules_created}")
    print(f"Files uploaded: {uploaded}")
    if failed:
        print(f"Upload failures: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
