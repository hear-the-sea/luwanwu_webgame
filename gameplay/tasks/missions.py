from __future__ import annotations

import logging
import math

from celery import shared_task
from django.utils import timezone

from common.utils.celery import safe_apply_async_with_dedup
from gameplay.models import MissionRun
from gameplay.services.missions import finalize_mission_run

logger = logging.getLogger(__name__)

# 任务去重超时时间（秒）
_TASK_DEDUP_TIMEOUT = 5


@shared_task(name="gameplay.complete_mission", bind=True, max_retries=2, default_retry_delay=30)
def complete_mission_task(self, run_id: int):
    try:
        run = MissionRun.objects.select_related("mission", "manor").prefetch_related("guests").filter(pk=run_id).first()
        if not run:
            logger.warning("MissionRun %d not found", run_id)
            return "not_found"
        now = timezone.now()
        if run.return_at and run.return_at > now:
            remaining = math.ceil((run.return_at - now).total_seconds())
            if remaining > 0:
                # 使用去重机制避免并发重复调度
                dispatched = safe_apply_async_with_dedup(
                    complete_mission_task,
                    dedup_key=f"mission:complete:{run_id}",
                    dedup_timeout=_TASK_DEDUP_TIMEOUT,
                    args=[run_id],
                    countdown=remaining,
                    logger=logger,
                    log_message=f"mission task reschedule failed: run_id={run_id}",
                )
                if not dispatched:
                    raise RuntimeError(f"mission reschedule dispatch failed: run_id={run_id}")
                return "rescheduled"
        finalize_mission_run(run, now=now)
        return "completed"
    except Exception as exc:
        logger.exception("Failed to complete mission %d: %s", run_id, exc)
        raise self.retry(exc=exc)
