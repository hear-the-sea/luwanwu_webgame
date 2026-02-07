from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from gameplay.services.manor import finalize_building_upgrade

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.complete_building_upgrade", bind=True, max_retries=2, default_retry_delay=30)
def complete_building_upgrade(self, building_id: int):
    from gameplay.models import Building

    try:
        building = (
            Building.objects.select_related("manor", "manor__user", "building_type").filter(pk=building_id).first()
        )
        if not building:
            logger.warning(f"Building {building_id} not found")
            return "not_found"
        now = timezone.now()
        if building.upgrade_complete_at and building.upgrade_complete_at > now:
            remaining = int((building.upgrade_complete_at - now).total_seconds())
            if remaining > 0:
                complete_building_upgrade.apply_async(args=[building_id], countdown=remaining)
                return "rescheduled"
        finalized = finalize_building_upgrade(building, now=now, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete building upgrade {building_id}: {exc}")
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
    count = 0
    for building in qs:
        try:
            if finalize_building_upgrade(building, now=now, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize building {building.id}")
    return count
