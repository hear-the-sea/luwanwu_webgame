"""Raid combat package.

Import concrete submodules directly for implementation details, for example:

- `gameplay.services.raid.combat.battle`
- `gameplay.services.raid.combat.runs`
- `gameplay.services.raid.combat.loot`
"""

from __future__ import annotations

from .battle import process_raid_battle  # noqa: F401
from .runs import (  # noqa: F401
    can_raid_retreat,
    finalize_raid,
    get_active_raids,
    get_raid_history,
    refresh_raid_runs,
    request_raid_retreat,
    start_raid,
)
from .travel import calculate_raid_travel_time, get_active_raid_count, get_incoming_raids  # noqa: F401

__all__ = [
    # travel
    "calculate_raid_travel_time",
    "get_active_raid_count",
    "get_incoming_raids",
    # raid lifecycle
    "start_raid",
    "process_raid_battle",
    "finalize_raid",
    "request_raid_retreat",
    "can_raid_retreat",
    "refresh_raid_runs",
    "get_active_raids",
    "get_raid_history",
]
