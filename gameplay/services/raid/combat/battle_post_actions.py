from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Callable

from django.utils import timezone


def fail_raid_run_due_missing_manor(
    locked_run: Any,
    *,
    now: datetime | None,
    guest_model: Any,
    guest_status: Any,
    manor_model: Any,
    normalize_positive_int_mapping: Callable[[Any], dict[str, int]],
    add_troops_batch: Callable[..., Any],
) -> None:
    now = now or timezone.now()

    guests = list(locked_run.guests.select_for_update())
    guests_to_update = []
    for guest in guests:
        if guest.status == guest_status.DEPLOYED:
            guest.status = guest_status.IDLE
            guests_to_update.append(guest)
    if guests_to_update:
        guest_model.objects.bulk_update(guests_to_update, ["status"])

    attacker_locked = manor_model.objects.select_for_update().filter(pk=locked_run.attacker_id).first()
    if attacker_locked is not None:
        loadout = normalize_positive_int_mapping(getattr(locked_run, "troop_loadout", {}))
        if loadout:
            add_troops_batch(attacker_locked, loadout)
        locked_run.attacker = attacker_locked

    locked_run.status = locked_run.Status.COMPLETED
    locked_run.is_attacker_victory = False
    locked_run.return_at = now
    locked_run.completed_at = now
    locked_run.save(update_fields=["status", "is_attacker_victory", "return_at", "completed_at"])


def dispatch_complete_raid_task(
    run: Any,
    *,
    now: datetime | None,
    logger: logging.Logger,
    safe_apply_async_fn: Callable[..., bool],
    complete_raid_task_importer: Callable[[], Any],
    finalize_raid_fn: Callable[..., Any],
) -> None:
    current_time = now or timezone.now()

    def _fallback_sync_when_due(remaining_seconds: int) -> None:
        if remaining_seconds > 0:
            return
        logger.warning("complete_raid_task dispatch failed for due raid; finalizing synchronously: run_id=%s", run.id)
        finalize_raid_fn(run, now=current_time)

    try:
        complete_raid_task = complete_raid_task_importer()
    except ImportError as exc:
        logger.warning(
            "complete_raid_task import failed: run_id=%s error=%s",
            run.id,
            exc,
            exc_info=True,
            extra={"degraded": True, "component": "raid_task_import", "run_id": run.id},
        )
        remaining = 0 if not run.return_at else max(0, math.ceil((run.return_at - current_time).total_seconds()))
        _fallback_sync_when_due(remaining)
        return
    except Exception:
        logger.error(
            "Unexpected complete_raid_task import failure: run_id=%s",
            run.id,
            exc_info=True,
            extra={"degraded": True, "component": "raid_task_import", "run_id": run.id},
        )
        raise

    if run.return_at:
        remaining = max(0, math.ceil((run.return_at - current_time).total_seconds()))
    else:
        remaining = max(0, int(run.travel_time or 0))
    dispatched = safe_apply_async_fn(
        complete_raid_task,
        args=[run.id],
        countdown=remaining,
        logger=logger,
        log_message="complete_raid_task dispatch failed",
    )
    if not dispatched:
        _fallback_sync_when_due(remaining)
