from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ============ Horse Production ============


@shared_task(name="gameplay.complete_horse_production", bind=True, max_retries=2, default_retry_delay=30)
def complete_horse_production(self, production_id: int):
    """
    Complete horse production background task.
    """
    from gameplay.models import HorseProduction
    from gameplay.services.stable import finalize_horse_production

    try:
        production = (
            HorseProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"HorseProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_horse_production.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_horse_production(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete horse production {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_horse_productions")
def scan_horse_productions(limit: int = 200):
    """
    Scan and complete all overdue horse productions (for worker downtime recovery).
    """
    from gameplay.models import HorseProduction
    from gameplay.services.stable import finalize_horse_production

    now = timezone.now()
    qs = (
        HorseProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=HorseProduction.Status.PRODUCING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0

    for production in qs:
        try:
            if finalize_horse_production(production, send_notification=True):
                count += 1
        except Exception as exc:
            logger.exception("Failed to finalize horse production %s: %s", production.id, exc)
    return count


# ============ Livestock Production ============


@shared_task(name="gameplay.complete_livestock_production", bind=True, max_retries=2, default_retry_delay=30)
def complete_livestock_production(self, production_id: int):
    """
    Complete livestock production background task.
    """
    from gameplay.models import LivestockProduction
    from gameplay.services.ranch import finalize_livestock_production

    try:
        production = (
            LivestockProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"LivestockProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_livestock_production.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_livestock_production(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete livestock production {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_livestock_productions")
def scan_livestock_productions(limit: int = 200):
    """
    Scan and complete all overdue livestock productions (for worker downtime recovery).
    """
    from gameplay.models import LivestockProduction
    from gameplay.services.ranch import finalize_livestock_production

    now = timezone.now()
    qs = (
        LivestockProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=LivestockProduction.Status.PRODUCING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0

    for production in qs:
        try:
            if finalize_livestock_production(production, send_notification=True):
                count += 1
        except Exception as exc:
            logger.exception("Failed to finalize livestock production %s: %s", production.id, exc)
    return count


# ============ Smelting Production ============


@shared_task(name="gameplay.complete_smelting_production", bind=True, max_retries=2, default_retry_delay=30)
def complete_smelting_production(self, production_id: int):
    """
    Complete metal smelting background task.
    """
    from gameplay.models import SmeltingProduction
    from gameplay.services.smithy import finalize_smelting_production

    try:
        production = (
            SmeltingProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"SmeltingProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_smelting_production.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_smelting_production(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete smelting production {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_smelting_productions")
def scan_smelting_productions(limit: int = 200):
    """
    Scan and complete all overdue metal smelting (for worker downtime recovery).
    """
    from gameplay.models import SmeltingProduction
    from gameplay.services.smithy import finalize_smelting_production

    now = timezone.now()
    qs = (
        SmeltingProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=SmeltingProduction.Status.PRODUCING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0

    for production in qs:
        try:
            if finalize_smelting_production(production, send_notification=True):
                count += 1
        except Exception as exc:
            logger.exception("Failed to finalize smelting production %s: %s", production.id, exc)
    return count


# ============ Equipment Forging ============


@shared_task(name="gameplay.complete_equipment_forging", bind=True, max_retries=2, default_retry_delay=30)
def complete_equipment_forging(self, production_id: int):
    """
    Complete equipment forging background task.
    """
    from gameplay.models import EquipmentProduction
    from gameplay.services.forge import finalize_equipment_forging

    try:
        production = (
            EquipmentProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"EquipmentProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_equipment_forging.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_equipment_forging(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete equipment forging {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_equipment_forgings")
def scan_equipment_forgings(limit: int = 200):
    """
    Scan and complete all overdue equipment forging (for worker downtime recovery).
    """
    from gameplay.models import EquipmentProduction
    from gameplay.services.forge import finalize_equipment_forging

    now = timezone.now()
    qs = (
        EquipmentProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=EquipmentProduction.Status.FORGING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0

    for production in qs:
        try:
            if finalize_equipment_forging(production, send_notification=True):
                count += 1
        except Exception as exc:
            logger.exception("Failed to finalize equipment forging %s: %s", production.id, exc)
    return count


# ============ Work Assignments ============


@shared_task(name="gameplay.complete_work_assignments")
def complete_work_assignments_task():
    """
    Periodically complete expired work assignments.
    Runs every minute.
    """
    from gameplay.services.work import complete_work_assignments
    try:
        count = complete_work_assignments()
        return f"完成 {count} 个打工任务"
    except Exception:
        logger.exception("Failed to complete work assignments")
        raise
