from __future__ import annotations

import logging
import math

from celery import shared_task
from django.utils import timezone

from common.utils.celery import safe_apply_async_with_dedup
from gameplay.services.technology import finalize_technology_upgrade

logger = logging.getLogger(__name__)

# 任务去重超时时间（秒）
_TASK_DEDUP_TIMEOUT = 5


@shared_task(name="gameplay.complete_technology_upgrade", bind=True, max_retries=2, default_retry_delay=30)
def complete_technology_upgrade(self, tech_id: int):
    """
    Complete technology upgrade background task.
    """
    from gameplay.models import PlayerTechnology

    try:
        tech = PlayerTechnology.objects.select_related("manor", "manor__user").filter(pk=tech_id).first()
        if not tech:
            logger.warning("PlayerTechnology %d not found", tech_id)
            return "not_found"
        now = timezone.now()
        if tech.upgrade_complete_at and tech.upgrade_complete_at > now:
            remaining = math.ceil((tech.upgrade_complete_at - now).total_seconds())
            if remaining > 0:
                dispatched = safe_apply_async_with_dedup(
                    complete_technology_upgrade,
                    dedup_key=f"technology:upgrade:{tech_id}",
                    dedup_timeout=_TASK_DEDUP_TIMEOUT,
                    args=[tech_id],
                    countdown=remaining,
                    logger=logger,
                    log_message=f"technology upgrade reschedule failed: tech_id={tech_id}",
                )
                if not dispatched:
                    raise RuntimeError(f"technology reschedule dispatch failed: tech_id={tech_id}")
                return "rescheduled"
        finalized = finalize_technology_upgrade(tech, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception("Failed to complete technology upgrade %d: %s", tech_id, exc)
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_technology_upgrades")
def scan_technology_upgrades(limit: int = 200):
    """
    Scan and complete all overdue technology upgrades (for worker downtime recovery).
    """
    from gameplay.models import PlayerTechnology

    now = timezone.now()
    qs = (
        PlayerTechnology.objects.select_related("manor", "manor__user")
        .filter(is_upgrading=True, upgrade_complete_at__lte=now)
        .order_by("upgrade_complete_at")[:limit]
    )
    count = 0
    for tech in qs:
        try:
            if finalize_technology_upgrade(tech, send_notification=True):
                count += 1
        except Exception:
            logger.exception("Failed to finalize technology %d", tech.id)
    return count
