from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from common.utils.celery import safe_apply_async_with_dedup
from gameplay.services.manor.core import finalize_building_upgrade

from ._scheduled import DEFAULT_TASK_DEDUP_TIMEOUT, count_finalized_records, maybe_reschedule_for_future

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.complete_building_upgrade", bind=True, max_retries=2, default_retry_delay=30)
def complete_building_upgrade(self, building_id: int):
    from gameplay.models import Building

    try:
        building = (
            Building.objects.select_related("manor", "manor__user", "building_type").filter(pk=building_id).first()
        )
        if not building:
            logger.warning("Building %d not found", building_id)
            return "not_found"
        rescheduled, now = maybe_reschedule_for_future(
            task_func=complete_building_upgrade,
            record_id=building_id,
            eta_value=building.upgrade_complete_at,
            dedup_key=f"building:upgrade:{building_id}",
            schedule_func=safe_apply_async_with_dedup,
            logger=logger,
            now_func=timezone.now,
            log_message=f"building upgrade reschedule failed: building_id={building_id}",
            failure_message=f"building upgrade reschedule dispatch failed: building_id={building_id}",
            dedup_timeout=DEFAULT_TASK_DEDUP_TIMEOUT,
        )
        if rescheduled is not None:
            return rescheduled
        finalized = finalize_building_upgrade(building, now=now, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception("Failed to complete building upgrade %d: %s", building_id, exc)
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_building_upgrades")
def scan_building_upgrades(limit: int = 200):
    """
    Fallback scan to complete any overdue upgrades (in case of worker downtime).
    """
    from gameplay.models import Building

    now = timezone.now()
    qs = (
        Building.objects.select_related("manor", "manor__user", "building_type")
        .filter(is_upgrading=True, upgrade_complete_at__lte=now)
        .order_by("upgrade_complete_at")[:limit]
    )
    return count_finalized_records(
        qs,
        finalize=lambda building: finalize_building_upgrade(building, now=now, send_notification=True),
        logger=logger,
        error_message="Failed to finalize building %s: %s",
    )
