"""Raid input validation helpers extracted from raid run orchestration."""

from __future__ import annotations

from typing import Dict, List

from gameplay.services.raid import combat as combat_pkg
from guests.models import Guest, GuestStatus

from ....models import Manor
from .travel import get_active_raid_count


def _get_active_raid_count(attacker: Manor) -> int:
    """Prefer the runs-module alias so existing monkeypatch sites keep working."""
    from . import runs as combat_runs

    active_count_fn = getattr(combat_runs, "get_active_raid_count", get_active_raid_count)
    return active_count_fn(attacker)


def _validate_and_normalize_raid_inputs(
    attacker: Manor,
    defender: Manor,
    guest_ids: List[int],
    troop_loadout: Dict[str, int] | None,
) -> tuple[List[int], Dict[str, int]]:
    from ..utils import can_attack_target

    can_attack, reason = can_attack_target(attacker, defender, use_cached_recent_attacks=False)
    if not can_attack:
        raise ValueError(reason)

    active_count = _get_active_raid_count(attacker)
    if active_count >= combat_pkg.PVPConstants.RAID_MAX_CONCURRENT:
        raise ValueError(f"同时最多进行 {combat_pkg.PVPConstants.RAID_MAX_CONCURRENT} 次出征")

    if not guest_ids:
        raise ValueError("请选择至少一名门客")
    if not isinstance(guest_ids, list):
        raise ValueError("门客参数无效")
    try:
        normalized_guest_ids = [int(gid) for gid in guest_ids]
    except (TypeError, ValueError):
        raise ValueError("门客参数无效")

    normalized_troop_loadout = troop_loadout or {}
    if not isinstance(normalized_troop_loadout, dict):
        raise ValueError("护院配置无效")
    return normalized_guest_ids, normalized_troop_loadout


def _load_and_validate_attacker_guests(attacker: Manor, guest_ids: List[int]) -> list[Guest]:
    guests = list(
        attacker.guests.select_for_update()
        .filter(id__in=guest_ids)
        .select_related("template")
        .prefetch_related("skills")
    )

    if len(guests) != len(set(guest_ids)):
        raise ValueError("部分门客不可用或已离开庄园")

    max_squad_size = getattr(attacker, "max_squad_size", None) or 0
    if max_squad_size and len(guests) > max_squad_size:
        raise ValueError(f"最多只能派出 {max_squad_size} 名门客出征")

    for guest in guests:
        if guest.status != GuestStatus.IDLE:
            raise ValueError(f"门客 {guest.display_name} 当前不可出征")
    return guests


def _normalize_and_validate_raid_loadout(guests: list[Guest], troop_loadout: Dict[str, int]) -> Dict[str, int]:
    from battle.combatants import normalize_troop_loadout
    from battle.services import validate_troop_capacity

    loadout = normalize_troop_loadout(troop_loadout, default_if_empty=False)
    loadout = {key: count for key, count in loadout.items() if count > 0}
    validate_troop_capacity(guests, loadout)
    return loadout
