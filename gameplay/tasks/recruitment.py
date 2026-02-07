from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.complete_troop_recruitment", bind=True, max_retries=2, default_retry_delay=30)
def complete_troop_recruitment(self, recruitment_id: int):
    """
    Complete troop recruitment background task.
    """
    from gameplay.models import TroopRecruitment
    from gameplay.services.recruitment import finalize_troop_recruitment

    try:
        recruitment = (
            TroopRecruitment.objects
            .select_related("manor", "manor__user")
            .filter(pk=recruitment_id)
            .first()
        )
        if not recruitment:
            logger.warning(f"TroopRecruitment {recruitment_id} not found")
            return "not_found"

        now = timezone.now()
        if recruitment.complete_at and recruitment.complete_at > now:
            remaining = int((recruitment.complete_at - now).total_seconds())
            if remaining > 0:
                complete_troop_recruitment.apply_async(args=[recruitment_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_troop_recruitment(recruitment, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception("Failed to complete troop recruitment %s: %s", recruitment_id, exc)
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_troop_recruitments")
def scan_troop_recruitments(limit: int = 200):
    """
    Scan and complete all overdue troop recruitments (for worker downtime recovery).
    """
    from gameplay.models import TroopRecruitment
    from gameplay.services.recruitment import finalize_troop_recruitment

    now = timezone.now()
    qs = (
        TroopRecruitment.objects
        .select_related("manor", "manor__user")
        .filter(status=TroopRecruitment.Status.RECRUITING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0
    for recruitment in qs:
        try:
            if finalize_troop_recruitment(recruitment, send_notification=True):
                count += 1
        except Exception as exc:
            logger.exception("Failed to finalize troop recruitment %s: %s", recruitment.id, exc)
    return count
