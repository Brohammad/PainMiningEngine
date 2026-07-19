"""Process logging configuration."""

from logging.config import dictConfig
from typing import Any

from backend.app.config.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Configure standard-library logging for an explicitly supplied runtime."""

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "backend.app.observability.logging.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "level": settings.log_level,
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": settings.log_level,
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }
    dictConfig(config)
