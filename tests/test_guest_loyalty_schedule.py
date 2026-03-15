from __future__ import annotations

from django.conf import settings


def test_process_daily_loyalty_is_routed_to_timer_queue():
    assert settings.CELERY_TASK_ROUTES["guests.process_daily_loyalty"] == {"queue": settings.CELERY_TIMER_QUEUE}


def test_process_daily_loyalty_is_scheduled_at_midnight():
    entry = settings.CELERY_BEAT_SCHEDULE["process-daily-guest-loyalty"]

    assert entry["task"] == "guests.process_daily_loyalty"
    assert entry["schedule"]._orig_hour == 0
    assert entry["schedule"]._orig_minute == 0
