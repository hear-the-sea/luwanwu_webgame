from __future__ import annotations

"""
Compatibility wrapper for the project's Celery application.

The canonical Celery app lives in `config/celery.py` and is exposed as
`config.celery.app` / `config.celery_app`. This module keeps the historical
import path (`tasks.celery.celery_app`) working.
"""

from config.celery import app as celery_app

__all__ = ("celery_app",)
