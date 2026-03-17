from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from django.db import transaction
from django.utils import timezone


def request_raid_retreat(
    run: Any,
    *,
    raid_run_model: Any,
    schedule_retreat_completion: Callable[[int, int], None],
) -> None:
    if run.status != raid_run_model.Status.MARCHING:
        raise ValueError("当前状态无法撤退")

    if run.is_retreating:
        raise ValueError("已在撤退中")

    now = timezone.now()
    elapsed = max(0, int((now - run.started_at).total_seconds()))

    with transaction.atomic():
        locked_run = raid_run_model.objects.select_for_update().filter(pk=run.pk).first()
        if not locked_run or locked_run.status != raid_run_model.Status.MARCHING:
            raise ValueError("当前状态无法撤退")
        if locked_run.is_retreating:
            raise ValueError("已在撤退中")

        locked_run.is_retreating = True
        locked_run.status = raid_run_model.Status.RETREATED
        locked_run.return_at = now + timedelta(seconds=max(1, elapsed))
        locked_run.save(update_fields=["is_retreating", "status", "return_at"])

    schedule_retreat_completion(run.id, max(1, elapsed))


def finalize_raid_retreat(
    run: Any,
    *,
    now: Any = None,
    normalize_positive_int_mapping: Callable[[Any], dict[str, int]],
    add_troops_batch: Callable[[Any, dict[str, int]], None],
    completed_status: Any,
) -> None:
    from guests.models import Guest, GuestStatus

    now = now or timezone.now()

    guests = list(run.guests.select_for_update())
    guests_to_update = []
    for guest in guests:
        if guest.status == GuestStatus.DEPLOYED:
            guest.status = GuestStatus.IDLE
            guests_to_update.append(guest)
    if guests_to_update:
        Guest.objects.bulk_update(guests_to_update, ["status"])

    loadout = normalize_positive_int_mapping(getattr(run, "troop_loadout", {}))
    if loadout:
        add_troops_batch(run.attacker, loadout)

    run.status = completed_status
    run.completed_at = now
    run.save(update_fields=["status", "completed_at"])


def can_raid_retreat(run: Any, *, marching_status: Any, now: Any = None) -> bool:
    del now
    if run.status != marching_status:
        return False
    if run.is_retreating:
        return False
    return True
