"""Central logging configuration for the web app."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import PROJECT_ROOT

LOG_FILE = PROJECT_ROOT / "app.log"
LOGGER_NAME = "easylearn"

_THIRD_PARTY_LOGGERS = (
    "canvasapi",
    "pylti1p3",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
)


def configure_logging() -> logging.Logger:
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not root_logger.handlers:
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)

    for logger_name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).addHandler(file_handler)

    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(logging.INFO)
    return app_logger
