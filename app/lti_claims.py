"""LTI claim helpers."""

from __future__ import annotations

# Canonical LIS role names (full URNs like
# "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor" are reduced to
# their final path segment before matching, so substring collisions such as
# "LibraryAssistant" can never grant teaching privileges).
_ROLE_SEGMENTS = {
    "Administrator": frozenset({"Administrator", "SysAdmin"}),
    "Teacher": frozenset({"Instructor", "ContentDeveloper"}),
    # TAs deliberately get teaching-equivalent access (see dependencies.py).
    "Teaching Assistant": frozenset({"TeachingAssistant", "TeachingAssistantGradePermission"}),
    "Student": frozenset({"Learner", "Student", "Member", "Mentor"}),
}


def _role_segments(roles: list) -> set[str]:
    """Extract the final segment of every LTI role string (case-insensitive)."""
    segments: set[str] = set()
    for role in roles or []:
        text = str(role).strip()
        if not text:
            continue
        segments.add(text.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower())
    return segments


def extract_lti_user_fields(launch_data: dict) -> dict[str, str | None]:
    """Parse display fields from an LTI 1.3 launch JWT body."""
    custom = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/custom", {}) or {}
    segments = _role_segments(launch_data.get("https://purl.imsglobal.org/spec/lti/claim/roles") or [])

    user_role = None
    for role_name, matches in _ROLE_SEGMENTS.items():
        if segments & {m.lower() for m in matches}:
            user_role = role_name
            break

    given = launch_data.get("given_name") or ""
    family = launch_data.get("family_name") or ""
    composed = f"{given} {family}".strip() or None

    canvas_user_id = custom.get("canvas_user_id") or custom.get("custom_canvas_user_id")
    return {
        "user_name": (
            launch_data.get("name")
            or composed
            or launch_data.get("given_name")
            or custom.get("person_name_full")
        ),
        "user_email": launch_data.get("email") or custom.get("person_email"),
        "user_role": user_role,
        "lti_sub": launch_data.get("sub"),
        "canvas_user_id": str(canvas_user_id) if canvas_user_id else None,
    }
