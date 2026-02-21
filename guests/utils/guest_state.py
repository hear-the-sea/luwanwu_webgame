from __future__ import annotations

from typing import Iterable

from django.utils import timezone

from guests.models import MAX_GUEST_LEVEL, Guest
from guests.services.equipment import apply_set_bonuses
from guests.services.health import recover_guest_hp
from guests.services.training import ensure_auto_training, finalize_guest_training


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
    finalize_guest_training(guest, now=now)
    if auto_train and guest.level < MAX_GUEST_LEVEL and not guest.training_complete_at:
        ensure_auto_training(guest)
    if recover_hp:
        recover_guest_hp(guest, now=now)
    if apply_sets:
        apply_set_bonuses(guest)
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
