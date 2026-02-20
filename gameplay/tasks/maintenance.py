from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.cleanup_old_data")
def cleanup_old_data_task():
    """
    Clean up expired transaction records to save database space.

    Runs daily at midnight, cleans up:
    - ResourceEvent: keep 30 days
    - Other log tables handled by their respective module tasks
    """
    from gameplay.models import ResourceEvent

    cutoff = timezone.now() - timedelta(days=30)
    deleted, _ = ResourceEvent.objects.filter(created_at__lt=cutoff).delete()

    logger.info("Cleaned up %d resource event records older than 30 days", deleted)
    return deleted


@shared_task(name="gameplay.decay_prisoner_loyalty")
def decay_prisoner_loyalty_task():
    """
    Daily decay of prisoner loyalty.

    Runs daily, reduces loyalty of all held prisoners by specified amount (default 5).
    Loyalty cannot go below 0.
    """
    from gameplay.constants import PVPConstants
    from gameplay.models import JailPrisoner

    decay_amount = int(getattr(PVPConstants, "JAIL_LOYALTY_DAILY_DECAY", 5) or 5)

    # Batch update all held prisoners, reduce loyalty but not below 0
    updated = JailPrisoner.objects.filter(
        status=JailPrisoner.Status.HELD
    ).update(
        loyalty=Greatest(F("loyalty") - decay_amount, 0)
    )

    logger.info("Prisoner loyalty daily decay: updated %d prisoners, each reduced by %d", updated, decay_amount)
    return updated
