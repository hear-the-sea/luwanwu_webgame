from __future__ import annotations

import logging
from collections.abc import Callable

from core.utils.task_monitoring import increment_degraded_counter
from guests.models import Guest, GuestStatus

logger = logging.getLogger(__name__)

BATTLE_ORPHANED_DEPLOYED_RECOVERY_COUNTER = "battle_orphaned_deployed_recovery"


def collect_active_deployment_guest_ids(candidate_ids: list[int]) -> set[int]:
    if not candidate_ids:
        return set()

    from gameplay.models import ArenaEntry, ArenaEntryGuest, ArenaTournament, MissionRun, RaidRun

    active_ids = set(
        MissionRun.objects.filter(status=MissionRun.Status.ACTIVE, guests__id__in=candidate_ids).values_list(
            "guests__id", flat=True
        )
    )
    active_ids.update(
        RaidRun.objects.filter(
            status__in=[
                RaidRun.Status.MARCHING,
                RaidRun.Status.BATTLING,
                RaidRun.Status.RETURNING,
                RaidRun.Status.RETREATED,
            ],
            guests__id__in=candidate_ids,
        ).values_list("guests__id", flat=True)
    )
    active_ids.update(
        ArenaEntryGuest.objects.filter(
            guest_id__in=candidate_ids,
            entry__status=ArenaEntry.Status.REGISTERED,
            entry__tournament__status__in=[
                ArenaTournament.Status.RECRUITING,
                ArenaTournament.Status.RUNNING,
            ],
        ).values_list("guest_id", flat=True)
    )
    return active_ids


def find_orphaned_deployed_guest_ids(candidate_ids: list[int]) -> list[int]:
    if not candidate_ids:
        return []

    active_ids = collect_active_deployment_guest_ids(candidate_ids)
    return [guest_id for guest_id in candidate_ids if guest_id not in active_ids]


def record_orphaned_guest_recovery(
    orphaned_ids: list[int],
    recovered_count: int,
    *,
    logger_override=None,
    increment_counter_fn: Callable[[str], None] = increment_degraded_counter,
) -> None:
    if recovered_count <= 0:
        return

    increment_counter_fn(BATTLE_ORPHANED_DEPLOYED_RECOVERY_COUNTER)
    active_logger = logger_override or logger
    active_logger.warning(
        "Recovered orphaned deployed guests before battle reuse: guest_ids=%s count=%s counter=%s",
        orphaned_ids,
        recovered_count,
        BATTLE_ORPHANED_DEPLOYED_RECOVERY_COUNTER,
    )


def recover_orphaned_deployed_guests(
    *,
    guest_model: type[Guest] = Guest,
    deployed_status: str = GuestStatus.DEPLOYED,
    idle_status: str = GuestStatus.IDLE,
    guest_ids: list[int] | None = None,
    find_orphaned_deployed_guest_ids_fn: Callable[[list[int]], list[int]] = find_orphaned_deployed_guest_ids,
    record_orphaned_guest_recovery_fn: Callable[[list[int], int], None],
) -> int:
    deployed_guests = guest_model.objects.filter(status=deployed_status)
    if guest_ids is not None:
        deployed_guests = deployed_guests.filter(id__in=guest_ids)

    candidate_ids = list(deployed_guests.order_by("id").values_list("id", flat=True))
    if not candidate_ids:
        return 0

    orphaned_ids = find_orphaned_deployed_guest_ids_fn(candidate_ids)
    if not orphaned_ids:
        return 0

    recovered_count = guest_model.objects.filter(id__in=orphaned_ids, status=deployed_status).update(status=idle_status)
    record_orphaned_guest_recovery_fn(orphaned_ids, recovered_count)
    return recovered_count


def recover_orphaned_locked_guest_statuses(
    locked_guests: list[Guest],
    *,
    guest_model: type[Guest] = Guest,
    deployed_status: str = GuestStatus.DEPLOYED,
    idle_status: str = GuestStatus.IDLE,
    find_orphaned_deployed_guest_ids_fn: Callable[[list[int]], list[int]] = find_orphaned_deployed_guest_ids,
    record_orphaned_guest_recovery_fn: Callable[[list[int], int], None],
) -> int:
    deployed_ids = [
        guest.id for guest in locked_guests if getattr(guest, "status", None) == deployed_status and guest.id
    ]
    orphaned_ids = set(find_orphaned_deployed_guest_ids_fn(deployed_ids))
    if not orphaned_ids:
        return 0

    recovered_count = guest_model.objects.filter(id__in=orphaned_ids, status=deployed_status).update(status=idle_status)
    record_orphaned_guest_recovery_fn(sorted(orphaned_ids), recovered_count)

    for guest in locked_guests:
        if guest.id in orphaned_ids and getattr(guest, "status", None) == deployed_status:
            guest.status = idle_status
    return recovered_count
