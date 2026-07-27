"""Application-level exception hierarchy.

All known error states the app raises explicitly should use these classes so
global handlers in main.py can return consistent JSON responses.
"""

from __future__ import annotations

import logging


class AppError(Exception):
    """Base for typed, predictable application errors.

    Every instance carries a user-facing ``detail`` and a server-side
    ``log_msg`` so the global handler can log *and* respond in one place.
    """

    def __init__(
        self,
        detail: str = "Internal Server Error",
        *,
        status_code: int = 500,
        log_msg: str = "",
        log_level: int = logging.WARNING,
    ):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.log_msg = log_msg
        self.log_level = log_level
