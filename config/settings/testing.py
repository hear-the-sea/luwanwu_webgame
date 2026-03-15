"""
Test environment overrides.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


CELERY_ENV_VARS_TO_CLEAR = (
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "CELERY_BROKER_READ_URL",
    "CELERY_BROKER_WRITE_URL",
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _clear_celery_env_vars() -> None:
    for key in CELERY_ENV_VARS_TO_CLEAR:
        os.environ.pop(key, None)


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Force in-memory broker/backend during hermetic test runs.
_clear_celery_env_vars()

CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = _env_flag("DJANGO_TEST_CELERY_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER

try:
    from config.celery import app as celery_app

    celery_app.conf.update(
        CELERY_BROKER_URL=CELERY_BROKER_URL,
        CELERY_RESULT_BACKEND=CELERY_RESULT_BACKEND,
        CELERY_TASK_ALWAYS_EAGER=CELERY_TASK_ALWAYS_EAGER,
        CELERY_TASK_EAGER_PROPAGATES=CELERY_TASK_EAGER_PROPAGATES,
        broker_url=CELERY_BROKER_URL,
        result_backend=CELERY_RESULT_BACKEND,
        task_always_eager=CELERY_TASK_ALWAYS_EAGER,
        task_eager_propagates=CELERY_TASK_EAGER_PROPAGATES,
    )
except Exception:
    logger.warning("Failed to update Celery app for tests", exc_info=True)
