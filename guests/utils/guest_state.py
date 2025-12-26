from __future__ import annotations

from typing import Iterable

from django.utils import timezone

from guests import services as guest_services
from guests.models import Guest, MAX_GUEST_LEVEL


def refresh_guest_state(
    guest: Guest,
    *,
    now: timezone.datetime | None = None,
    auto_train: bool = True,
    apply_sets: bool = True,
    recover_hp: bool = True,
    refresh: bool = False,
) -> Guest:
    now = now or timezone.now()
    guest_services.finalize_guest_training(guest, now=now)
    if auto_train and guest.level < MAX_GUEST_LEVEL and not guest.training_complete_at:
        guest_services.ensure_auto_training(guest)
    if recover_hp:
        guest_services.recover_guest_hp(guest, now=now)
    if apply_sets:
        guest_services.apply_set_bonuses(guest)
    if refresh:
        guest.refresh_from_db()
    return guest


def refresh_guests_state(
    guests: Iterable[Guest],
    *,
    now: timezone.datetime | None = None,
    auto_train: bool = True,
    apply_sets: bool = True,
    recover_hp: bool = True,
    refresh: bool = False,
) -> Iterable[Guest]:
    now = now or timezone.now()
    for guest in guests:
        refresh_guest_state(
            guest,
            now=now,
            auto_train=auto_train,
            apply_sets=apply_sets,
            recover_hp=recover_hp,
            refresh=refresh,
        )
    return guests
