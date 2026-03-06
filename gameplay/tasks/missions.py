from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from common.utils.celery import safe_apply_async_with_dedup
from gameplay.models import MissionRun
from gameplay.services.missions import finalize_mission_run

from ._scheduled import DEFAULT_TASK_DEDUP_TIMEOUT, maybe_reschedule_for_future

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.complete_mission", bind=True, max_retries=2, default_retry_delay=30)
def complete_mission_task(self, run_id: int):
    try:
        run = MissionRun.objects.select_related("mission", "manor").prefetch_related("guests").filter(pk=run_id).first()
        if not run:
            logger.warning("MissionRun %d not found", run_id)
            return "not_found"
        rescheduled, now = maybe_reschedule_for_future(
            task_func=complete_mission_task,
            record_id=run_id,
            eta_value=run.return_at,
            dedup_key=f"mission:complete:{run_id}",
            schedule_func=safe_apply_async_with_dedup,
            logger=logger,
            now_func=timezone.now,
            log_message=f"mission task reschedule failed: run_id={run_id}",
            failure_message=f"mission reschedule dispatch failed: run_id={run_id}",
            dedup_timeout=DEFAULT_TASK_DEDUP_TIMEOUT,
        )
        if rescheduled is not None:
            return rescheduled
        finalize_mission_run(run, now=now)
        return "completed"
    except Exception as exc:
        logger.exception("Failed to complete mission %d: %s", run_id, exc)
        raise self.retry(exc=exc)
