from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from gameplay.models import MissionRun
from gameplay.services.missions import finalize_mission_run

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.complete_mission", bind=True, max_retries=2, default_retry_delay=30)
def complete_mission_task(self, run_id: int):
    try:
        run = MissionRun.objects.select_related("mission", "manor").prefetch_related("guests").filter(pk=run_id).first()
        if not run:
            logger.warning(f"MissionRun {run_id} not found")
            return "not_found"
        now = timezone.now()
        if run.return_at and run.return_at > now:
            remaining = int((run.return_at - now).total_seconds())
            if remaining > 0:
                complete_mission_task.apply_async(args=[run_id], countdown=remaining)
                return "rescheduled"
        finalize_mission_run(run, now=now)
        return "completed"
    except Exception as exc:
        logger.exception(f"Failed to complete mission {run_id}: {exc}")
        raise self.retry(exc=exc)
