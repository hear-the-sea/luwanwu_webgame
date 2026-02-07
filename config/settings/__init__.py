"""
Django settings package.

This package organizes settings into logical modules:
- base: Core Django configuration (apps, middleware, templates, etc.)
- database: Database, cache, and Redis configuration
- security: SECRET_KEY, CSRF, CORS, SSL, HSTS settings
- celery_conf: Celery queues, routes, and beat schedule
- logging_conf: Logging configuration
- testing: Test environment overrides
"""
from __future__ import annotations

import sys
import warnings

# Base configuration
from .base import *  # noqa: F401, F403

# Database and cache configuration
from .database import *  # noqa: F401, F403

# Security configuration
from .security import *  # noqa: F401, F403

# Celery configuration
from .celery_conf import *  # noqa: F401, F403

# Logging configuration
from .logging_conf import *  # noqa: F401, F403

# Test environment overrides
# mypy sees differing dict literal shapes between prod and testing settings; this is OK.
if RUNNING_TESTS and env("DJANGO_TEST_USE_ENV_SERVICES", "0") != "1":  # type: ignore[name-defined]  # noqa: F405
    from .testing import *  # type: ignore[assignment]  # noqa: F401, F403

# Development environment warning
if DEBUG and not RUNNING_TESTS and env("DJANGO_WARN_DEBUG", "1") == "1":  # noqa: F405
    argv = " ".join(sys.argv)
    if any(token in argv for token in ("runserver", "daphne", "celery", "gunicorn", "uvicorn")):
        warnings.warn(
            "Running in DEBUG mode. Security features are relaxed. "
            "DO NOT use DEBUG=True in production!",
            RuntimeWarning,
        )
