#!/usr/bin/env python3
"""Generate a weekly quiz from course materials and upload to Canvas."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402, F401 — loads PROJECT_ROOT/.env
from config import PROJECT_ROOT

from canvas_client import get_canvas  # noqa: E402
from course_export import (  # noqa: E402
    get_week_module,
    load_course_data,
    normalize_week_label,
    resolve_export_root,
)
from material_extract import extract_week_text, validate_week_text  # noqa: E402
from quiz_deploy import deploy_quiz_to_canvas  # noqa: E402
from quiz_generate import generate_weekly_quiz  # noqa: E402

log = logging.getLogger(__name__)
CACHE_DIR = PROJECT_ROOT / "cache"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a weekly quiz from export materials via Gemini."
    )
    parser.add_argument(
        "--week",
        required=True,
        help="Week label (e.g. 1, 'Week 1', '6-7')",
    )
    parser.add_argument(
        "--course-id",
        type=int,
        default=None,
        help="Canvas course id (default: CANVAS_COURSE_ID from .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract + generate JSON; do not upload to Canvas",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract and print/save week text",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Generate quiz JSON but skip Canvas upload",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Use cache/week-N.txt for extracted text",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return parser.parse_args()


def cache_path(week_label: str) -> Path:
    normalized = normalize_week_label(week_label)
    slug = normalized.lower().replace(" ", "-")
    return CACHE_DIR / f"{slug}.txt"


def load_or_extract_text(
    export_root: Path,
    module: dict,
    week_label: str,
    use_cache: bool,
) -> str:
    path = cache_path(week_label)
    if use_cache and path.is_file():
        log.info("Loading cached text from %s", path)
        return path.read_text(encoding="utf-8")

    text = extract_week_text(export_root, module)
    week_name = module.get("name", normalize_week_label(week_label))
    validate_week_text(text, week_name)

    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        log.info("Cached text to %s", path)

    return text


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
    module = get_week_module(data, args.week)
    week_name = module.get("name", normalize_week_label(args.week))

    text = load_or_extract_text(
        export_root, module, args.week, use_cache=args.cache
    )

    if args.extract_only:
        print(text)
        print(f"\n--- {len(text)} characters extracted for {week_name} ---")
        return 0

    log.info("Generating quiz for %s (%s chars of material)", week_name, len(text))
    quiz = generate_weekly_quiz(week_name, text)
    quiz_json = quiz.model_dump_json(indent=2)

    if args.dry_run or args.no_upload:
        print(quiz_json)
        if args.dry_run:
            print("\n(dry-run: no Canvas upload)")
        else:
            print("\n(--no-upload: skipped Canvas)")
        return 0

    course_id = args.course_id or int(os.environ.get("CANVAS_COURSE_ID", "2"))
    canvas = get_canvas()
    course = canvas.get_course(course_id)

    deployed = deploy_quiz_to_canvas(course, week_name, quiz)
    base = os.environ.get("CANVAS_API_URL", "http://localhost:3000").rstrip("/")
    print()
    print(f"Quiz created (draft): {base}/courses/{course_id}/quizzes/{deployed.id}")
    print(f"Module: {week_name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.error("%s", exc)
        if logging.getLogger().level <= logging.DEBUG:
            raise
        sys.exit(1)
