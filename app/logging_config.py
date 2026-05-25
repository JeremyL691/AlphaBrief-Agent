from __future__ import annotations

import logging
import logging.config
from pathlib import Path

from app.config import settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    settings.ensure_dirs()
    log_path: Path = settings.logs_dir / "alphabrief.log"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": settings.log_level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": settings.log_level,
                    "filename": str(log_path),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": settings.log_level,
                "handlers": ["console", "file"],
            },
            "loggers": {
                # Quiet down noisy third parties — we still keep WARN+
                "urllib3": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "openai": {"level": "WARNING"},
            },
        }
    )
    _configured = True
