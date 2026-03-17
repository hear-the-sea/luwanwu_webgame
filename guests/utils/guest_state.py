from __future__ import annotations

from datetime import datetime
from typing import Iterable

from django.utils import timezone

from guests.models import Guest
from guests.services.equipment import apply_set_bonuses
from guests.services.health import recover_guest_hp
from guests.services.training import ensure_auto_training, finalize_guest_training
from guests.training_runtime import refresh_guest_state as _refresh_guest_state_impl


def refresh_guest_state(
    guest: Guest,
    *,
    now: datetime | None = None,
    auto_train: bool = True,
    apply_sets: bool = True,
    recover_hp: bool = True,
    refresh: bool = False,
) -> Guest:
    return _refresh_guest_state_impl(
        guest,
        now=now,
        auto_train=auto_train,
        apply_sets=apply_sets,
        recover_hp=recover_hp,
        refresh=refresh,
        finalize_guest_training_func=finalize_guest_training,
        ensure_auto_training_func=ensure_auto_training,
        recover_guest_hp_func=recover_guest_hp,
        apply_set_bonuses_func=apply_set_bonuses,
    )


def refresh_guests_state(
    guests: Iterable[Guest],
    *,
    now: datetime | None = None,
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
