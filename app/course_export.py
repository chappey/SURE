"""Parse Canvas offline viewer export (course-data.js)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

COURSE_DATA_PATTERN = re.compile(
    r"window\.COURSE_DATA\s*=\s*(\{.*\})\s*;?\s*$",
    re.DOTALL,
)


def load_course_data(export_root: Path) -> dict[str, Any]:
    """Load and parse course-data.js from an offline export directory."""
    data_file = export_root / "viewer" / "course-data.js"
    if not data_file.is_file():
        raise FileNotFoundError(f"Missing course data: {data_file}")

    text = data_file.read_text(encoding="utf-8")
    match = COURSE_DATA_PATTERN.search(text)
    if not match:
        raise ValueError(f"Could not parse COURSE_DATA from {data_file}")

    return json.loads(match.group(1))


def resolve_export_root(project_root: Path, export_dir: str) -> Path:
    """Resolve COURSE_EXPORT_DIR relative to project root."""
    root = Path(export_dir)
    if not root.is_absolute():
        root = project_root / root
    if not root.is_dir():
        raise FileNotFoundError(f"Course export directory not found: {root}")
    return root.resolve()


def attachment_path(export_root: Path, item: dict[str, Any]) -> Path:
    """Resolve an Attachment item to an on-disk file path."""
    if item.get("type") != "Attachment":
        raise ValueError(f"Not an attachment item: {item.get('title')!r}")

    rel = item.get("content")
    if not rel:
        raise ValueError(f"Attachment missing content path: {item.get('title')!r}")

    path = (export_root / rel).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Attachment file not found: {path}")
    return path


def normalize_week_label(week: str) -> str:
    """Normalize CLI week arg to module name (e.g. '1' -> 'Week 1')."""
    week = week.strip()
    if week.lower().startswith("week"):
        return week if week[4:5] in (" ", "-") else f"Week {week[4:]}"
    return f"Week {week}"


def get_week_module(data: dict[str, Any], week_label: str) -> dict[str, Any]:
    """Find a week module by label ('1', 'Week 1', 'Week 6-7')."""
    target = normalize_week_label(week_label)
    for module in data.get("modules", []):
        if module.get("name") == target:
            return module
    available = [
        m.get("name", "")
        for m in data.get("modules", [])
        if str(m.get("name", "")).startswith("Week")
    ]
    raise ValueError(
        f"Week module {target!r} not found. Available: {', '.join(available)}"
    )


def list_week_modules(data: dict[str, Any]) -> list[str]:
    """Return names of all Week* modules in export order."""
    return [
        m.get("name", "")
        for m in data.get("modules", [])
        if str(m.get("name", "")).startswith("Week")
    ]


def iter_attachments(
    data: dict[str, Any], export_root: Path
) -> list[tuple[str, dict[str, Any], Path]]:
    """Return (module_name, item, file_path) for every attachment in module order."""
    results: list[tuple[str, dict[str, Any], Path]] = []
    for module in data.get("modules", []):
        name = module.get("name", "")
        for item in module.get("items", []):
            if item.get("type") != "Attachment":
                continue
            results.append((name, item, attachment_path(export_root, item)))
    return results
