"""
Test environment overrides.
"""
from __future__ import annotations

import os

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

# Clear Celery env vars to use in-memory settings
for key in (
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "CELERY_BROKER_READ_URL",
    "CELERY_BROKER_WRITE_URL",
):
    os.environ.pop(key, None)

CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False

try:
    from config.celery import app as celery_app

    celery_app.conf.update(
        broker_url=CELERY_BROKER_URL,
        result_backend=CELERY_RESULT_BACKEND,
        task_always_eager=CELERY_TASK_ALWAYS_EAGER,
    )
except Exception:
    pass
