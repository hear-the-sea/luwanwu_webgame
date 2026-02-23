from __future__ import annotations

import logging

from celery import shared_task

from gameplay.services.arena.core import run_due_arena_rounds, start_ready_tournaments

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.scan_arena_tournaments")
def scan_arena_tournaments(limit: int = 20) -> dict[str, int]:
    started = 0
    processed = 0

    try:
        started = start_ready_tournaments(limit=limit)
    except Exception:
        logger.exception("arena tournament start scan failed")

    try:
        processed = run_due_arena_rounds(limit=limit)
    except Exception:
        logger.exception("arena tournament round scan failed")

    return {
        "started": int(started),
        "processed_rounds": int(processed),
    }
