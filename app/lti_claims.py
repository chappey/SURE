"""LTI claim helpers."""

from __future__ import annotations


def extract_lti_user_fields(launch_data: dict) -> dict[str, str | None]:
    """Parse display fields from an LTI 1.3 launch JWT body."""
    custom = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/custom", {}) or {}
    roles = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/roles") or []

    user_role = None
    for role in roles:
        role_str = str(role)
        if any(kw in role_str for kw in ("Instructor", "Teacher", "Faculty", "Staff")):
            user_role = "Teacher"
            break
        if any(kw in role_str for kw in ("Administrator", "Admin", "SysAdmin", "ContentDeveloper")):
            user_role = "Administrator"
            break
        if any(kw in role_str for kw in ("TeachingAssistant", "TA", "Assistant")):
            user_role = "Teaching Assistant"
            break
        if any(kw in role_str for kw in ("Learner", "Student")):
            user_role = "Student"
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
