from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db import transaction

from core.exceptions import GuestNotIdleError

from ..models import Guest, GuestStatus
from . import equipment as equipment_service


@dataclass(frozen=True)
class DismissGuestResult:
    guest_name: str
    gear_summary: Counter[str]


def dismiss_guest(guest: Guest) -> DismissGuestResult:
    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().filter(pk=guest.pk).first()
        if not locked_guest:
            raise ValueError("门客不存在")
        if locked_guest.status not in {GuestStatus.IDLE, GuestStatus.INJURED}:
            raise GuestNotIdleError(locked_guest)

        guest_name = locked_guest.display_name
        gear_items = list(locked_guest.gear_items.select_related("template"))
        gear_summary = Counter(gear.template.name for gear in gear_items)
        for gear in gear_items:
            equipment_service.unequip_guest_item(gear, locked_guest, allow_injured=True)
        locked_guest.delete()

    return DismissGuestResult(guest_name=guest_name, gear_summary=gear_summary)
