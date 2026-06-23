"""Canvas ID helpers (global vs local course IDs)."""

from __future__ import annotations

_CANVAS_GLOBAL_COURSE_OFFSET = 1000000000000000


def normalize_canvas_course_id(value: str | int | None) -> int | None:
    """Return the numeric Canvas course id used by the REST API."""
    if value is None or value == "":
        return None

    raw = str(value).strip()
    if ":" in raw:
        # deployment_id-style values are not course ids; use the segment before ':'
        head, _, tail = raw.partition(":")
        if head.isdigit() and tail and not tail.isdigit():
            raw = head

    try:
        course_id = int(raw)
    except ValueError:
        return None

    if course_id >= _CANVAS_GLOBAL_COURSE_OFFSET:
        course_id -= _CANVAS_GLOBAL_COURSE_OFFSET

    return course_id if course_id > 0 else None


def extract_course_id_from_lti_launch(launch_data: dict) -> int | None:
    """Parse course id from an LTI 1.3 launch JWT body."""
    custom = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/custom", {}) or {}
    for key in ("canvas_course_id", "custom_canvas_course_id"):
        parsed = normalize_canvas_course_id(custom.get(key))
        if parsed is not None:
            return parsed

    context = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/context", {}) or {}
    return normalize_canvas_course_id(context.get("id"))
