"""
Logging configuration.
"""

from __future__ import annotations

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "core.middleware.RequestIDFilter",
        }
    },
    "formatters": {
        "verbose": {
            "format": "[%(request_id)s] %(levelname)s %(asctime)s %(name)s:%(lineno)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
