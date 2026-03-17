from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .guest_rules import build_guest_stat_block
from .models import Guest


@dataclass(frozen=True)
class GuestCombatStats:
    attack: int
    defense: int
    intellect: int
    max_hp: int
    current_hp: int | None
    troop_capacity: int


def is_live_guest_model(guest: Any) -> bool:
    return isinstance(guest, Guest)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_min(value: Any, *, minimum: int) -> int | None:
    parsed = _coerce_int(value)
    if parsed is None:
        return None
    return max(minimum, parsed)


def resolve_guest_combat_stats(guest: Any) -> GuestCombatStats:
    raw_stats: dict[str, Any] = {}
    if is_live_guest_model(guest):
        raw_stats = build_guest_stat_block(guest)
    else:
        stat_block = getattr(guest, "stat_block", None)
        if callable(stat_block):
            payload = stat_block()
            if isinstance(payload, dict):
                raw_stats = payload

    attack = _coerce_min(raw_stats.get("attack"), minimum=1)
    if attack is None:
        attack = _coerce_min(getattr(guest, "attack", None), minimum=1) or 1

    defense = _coerce_min(raw_stats.get("defense"), minimum=1)
    if defense is None:
        defense = _coerce_min(getattr(guest, "defense", None), minimum=1) or 1

    intellect = _coerce_int(raw_stats.get("intellect"))
    if intellect is None:
        intellect = _coerce_int(getattr(guest, "intellect", None)) or 0

    max_hp = _coerce_min(raw_stats.get("hp"), minimum=1)
    if max_hp is None:
        max_hp = _coerce_min(getattr(guest, "max_hp", None), minimum=1) or 1

    current_hp = _coerce_min(getattr(guest, "current_hp", None), minimum=1)
    if current_hp is not None:
        current_hp = min(max_hp, current_hp)

    troop_capacity = _coerce_min(getattr(guest, "troop_capacity", None), minimum=0) or 0

    return GuestCombatStats(
        attack=attack,
        defense=defense,
        intellect=intellect,
        max_hp=max_hp,
        current_hp=current_hp,
        troop_capacity=troop_capacity,
    )
