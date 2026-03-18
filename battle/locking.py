from __future__ import annotations

from guests.models import Guest, GuestStatus


def collect_guest_ids(guests: list[Guest]) -> list[int]:
    return [int(guest.id) for guest in guests if guest.pk]


def collect_manor_ids(manor, *guest_groups: list[Guest] | None) -> list[int]:
    manor_ids: set[int] = set()
    if getattr(manor, "pk", None):
        manor_ids.add(int(manor.pk))

    for guests in guest_groups:
        for guest in guests or []:
            guest_manor_id = getattr(guest, "manor_id", None)
            if guest_manor_id is None:
                guest_manor = getattr(guest, "manor", None)
                guest_manor_id = getattr(guest_manor, "pk", None)
            if guest_manor_id is None:
                continue
            try:
                parsed_id = int(guest_manor_id)
            except (TypeError, ValueError):
                continue
            if parsed_id > 0:
                manor_ids.add(parsed_id)
    return sorted(manor_ids)


def lock_manor_rows(manor_ids: list[int]) -> None:
    if not manor_ids:
        return

    from gameplay.models import Manor

    locked_ids = set(
        Manor.objects.select_for_update().filter(pk__in=manor_ids).order_by("id").values_list("id", flat=True)
    )
    missing_ids = [manor_id for manor_id in manor_ids if manor_id not in locked_ids]
    if missing_ids:
        raise ValueError("部分庄园不存在，无法执行战斗")


def lock_guest_rows(guest_ids: list[int]) -> list[Guest]:
    return list(Guest.objects.select_for_update().filter(id__in=guest_ids).order_by("id"))


def validate_locked_guest_statuses(locked_guests: list[Guest]) -> None:
    for guest in locked_guests:
        if guest.status == GuestStatus.DEPLOYED:
            raise ValueError(f"门客 {guest.display_name} 正在战斗中，请稍后再试")
        if guest.status == GuestStatus.WORKING:
            raise ValueError(f"门客 {guest.display_name} 正在打工中，无法出征")
        if guest.status == GuestStatus.INJURED:
            raise ValueError(f"门客 {guest.display_name} 处于重伤状态，请先治疗")


def load_locked_battle_participants(
    guest_ids: list[int],
    *,
    primary_guest_ids: list[int],
    secondary_guest_ids: list[int],
    lock_guest_rows_fn=lock_guest_rows,
) -> tuple[list[Guest], list[Guest], list[Guest]]:
    locked_guests = lock_guest_rows_fn(guest_ids)
    locked_guest_map = {guest.id: guest for guest in locked_guests}
    missing_guest_ids = [guest_id for guest_id in guest_ids if guest_id not in locked_guest_map]
    if missing_guest_ids:
        raise ValueError("部分门客不存在，无法执行战斗")

    locked_primary = [locked_guest_map[guest_id] for guest_id in primary_guest_ids]
    locked_secondary = [locked_guest_map[guest_id] for guest_id in secondary_guest_ids]
    locked_participants = list({guest.id: guest for guest in locked_primary + locked_secondary}.values())
    return locked_primary, locked_secondary, locked_participants


def mark_locked_guests_deployed(locked_guests: list[Guest]) -> None:
    for guest in locked_guests:
        guest.status = GuestStatus.DEPLOYED
    if locked_guests:
        Guest.objects.bulk_update(locked_guests, ["status"])


def refresh_guest_instances(guests: list[Guest]) -> None:
    for guest in guests:
        if guest.pk:
            guest.refresh_from_db()


def release_deployed_guests(guest_ids: list[int]) -> None:
    Guest.objects.filter(id__in=guest_ids, status=GuestStatus.DEPLOYED).update(status=GuestStatus.IDLE)
