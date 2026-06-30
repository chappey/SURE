"""Canvas OAuth scopes EasyLearn may request (only when the key enforces scopes)."""

from __future__ import annotations

# Minimal set for quiz generation + deploy. Leave CANVAS_OAUTH_SCOPES empty in .env
# unless the Developer Key has "Enforce Scopes" enabled (configure_oauth.py --enforce-scopes).
EASYLEARN_OAUTH_SCOPES: tuple[str, ...] = (
    "url:GET|/api/v1/courses",
    "url:GET|/api/v1/courses/:id",
    "url:GET|/api/v1/courses/:course_id/files",
    "url:GET|/api/v1/files/:id",
    "url:GET|/api/v1/courses/:course_id/modules",
    "url:GET|/api/v1/courses/:course_id/modules/:module_id/items",
    "url:POST|/api/v1/courses/:course_id/modules/:module_id/items",
    "url:GET|/api/v1/courses/:course_id/quizzes/:id",
    "url:POST|/api/v1/courses/:course_id/quizzes",
    "url:PUT|/api/v1/courses/:course_id/quizzes/:id",
    "url:POST|/api/v1/courses/:course_id/quizzes/:quiz_id/questions",
    "url:GET|/api/v1/courses/:course_id/quizzes/:quiz_id/statistics",
    "url:GET|/api/v1/courses/:course_id/quizzes/:quiz_id/submissions",
)


def easylearn_oauth_scopes_space_separated() -> str:
    return " ".join(EASYLEARN_OAUTH_SCOPES)
