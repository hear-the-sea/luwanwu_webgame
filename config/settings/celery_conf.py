"""
Celery configuration - queues, routes, and beat schedule.
"""
from __future__ import annotations

import os

from celery.schedules import crontab
from kombu import Queue

from .base import env
from .database import REDIS_BROKER_URL, REDIS_PASSWORD, REDIS_RESULT_URL, _redis_url_with_password


CELERY_BROKER_URL = _redis_url_with_password(env("CELERY_BROKER_URL", REDIS_BROKER_URL), REDIS_PASSWORD)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    CELERY_BROKER_URL if "CELERY_BROKER_URL" in os.environ else REDIS_RESULT_URL,
)
CELERY_RESULT_BACKEND = _redis_url_with_password(CELERY_RESULT_BACKEND, REDIS_PASSWORD)

CELERY_DEFAULT_QUEUE = env("CELERY_DEFAULT_QUEUE", "default")
CELERY_BATTLE_QUEUE = env("CELERY_BATTLE_QUEUE", "battle")
CELERY_TIMER_QUEUE = env("CELERY_TIMER_QUEUE", "timer")
CELERY_TASK_DEFAULT_QUEUE = CELERY_DEFAULT_QUEUE

CELERY_TASK_QUEUES = (
    Queue(CELERY_DEFAULT_QUEUE),
    Queue(CELERY_BATTLE_QUEUE),
    Queue(CELERY_TIMER_QUEUE),
)

CELERY_TASK_ROUTES = {
    "battle.generate_report": {"queue": CELERY_BATTLE_QUEUE},
    "gameplay.complete_mission": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_building_upgrade": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.scan_building_upgrades": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_work_assignments": {"queue": CELERY_TIMER_QUEUE},
    "guests.complete_training": {"queue": CELERY_TIMER_QUEUE},
    "guests.scan_training": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_scout": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.scan_scout_records": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.process_raid_battle": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.complete_raid": {"queue": CELERY_TIMER_QUEUE},
    "gameplay.scan_raid_runs": {"queue": CELERY_TIMER_QUEUE},
}

CELERY_BEAT_SCHEDULE = {
    "scan-building-upgrades": {
        "task": "gameplay.scan_building_upgrades",
        "schedule": crontab(minute="*/10"),
    },
    "scan-guest-training": {
        "task": "guests.scan_training",
        "schedule": crontab(minute="*/10"),
    },
    "complete-work-assignments": {
        "task": "gameplay.complete_work_assignments",
        "schedule": crontab(minute="*/1"),
    },
    "refresh-shop-stock": {
        "task": "trade.refresh_shop_stock",
        "schedule": crontab(hour=0, minute=0),
    },
    "guild-tech-daily-production": {
        "task": "guilds.tech_daily_production",
        "schedule": crontab(hour=0, minute=0),
    },
    "reset-guild-weekly-stats": {
        "task": "guilds.reset_weekly_stats",
        "schedule": crontab(hour=0, minute=0, day_of_week=1),
    },
    "cleanup-old-guild-logs": {
        "task": "guilds.cleanup_old_logs",
        "schedule": crontab(hour=3, minute=0),
    },
    "scan-scout-records": {
        "task": "gameplay.scan_scout_records",
        "schedule": crontab(minute="*/5"),
    },
    "scan-raid-runs": {
        "task": "gameplay.scan_raid_runs",
        "schedule": crontab(minute="*/5"),
    },
    "process-expired-market-listings": {
        "task": "trade.process_expired_listings",
        "schedule": crontab(minute="*/2"),
    },
    "cleanup-old-resource-events": {
        "task": "gameplay.cleanup_old_data",
        "schedule": crontab(hour=4, minute=0),
    },
    "decay-prisoner-loyalty": {
        "task": "gameplay.decay_prisoner_loyalty",
        "schedule": crontab(hour=0, minute=0),
    },
    "settle-auction-round": {
        "task": "trade.settle_auction_round",
        "schedule": crontab(hour="0,12", minute=5),
    },
    "check-create-auction-round": {
        "task": "trade.create_auction_round",
        "schedule": crontab(hour=0, minute=10),
    },
}
