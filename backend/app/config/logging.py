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
            "standard": {
                "format": (
                    "%(asctime)s %(levelname)s %(name)s " "[%(process)d] %(message)s"
                ),
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": settings.log_level,
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": settings.log_level,
        },
    }
    dictConfig(config)
