from __future__ import annotations

from typing import Dict

from core.utils.time_scale import scale_duration


def normalize_mission_loadout(raw: Dict[str, int] | None) -> Dict[str, int]:
    from battle.troops import load_troop_templates

    from ...utils.resource_calculator import normalize_mission_loadout as normalize_loadout_util

    templates = load_troop_templates()
    if not templates:
        raise AssertionError("mission troop templates must not be empty")

    return normalize_loadout_util(raw, templates)


def travel_time_seconds(base_time: int, guests, troop_loadout: Dict[str, int]) -> int:
    from battle.troops import load_troop_templates

    from ...utils.resource_calculator import calculate_travel_time

    templates = load_troop_templates()
    if not templates and troop_loadout:
        raise AssertionError("mission troop templates must not be empty")
    travel_seconds = calculate_travel_time(base_time, guests, troop_loadout, templates)
    return scale_duration(travel_seconds, minimum=1)
