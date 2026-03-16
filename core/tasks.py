from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

CELERY_BEAT_HEARTBEAT_CACHE_KEY = "health:celery:beat:last_seen"
_HEARTBEAT_CACHE_TTL_BUFFER_SECONDS = 300


@shared_task(name="core.celery_health_ping")
def celery_health_ping() -> str:
    return "pong"


@shared_task(name="core.record_celery_beat_heartbeat", ignore_result=True)
def record_celery_beat_heartbeat() -> None:
    max_age_seconds = max(60, int(getattr(settings, "HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS", 180)))
    timeout = max_age_seconds + _HEARTBEAT_CACHE_TTL_BUFFER_SECONDS
    cache.set(CELERY_BEAT_HEARTBEAT_CACHE_KEY, timezone.now().timestamp(), timeout=timeout)
