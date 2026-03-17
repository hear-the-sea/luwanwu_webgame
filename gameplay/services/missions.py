"""任务管理服务稳定入口。

注意：不要把 `gameplay.services.missions` 变成 package（目录），否则
`from gameplay.services import missions` 和 Django/mypy 插件的加载路径会发生变化。
"""

from __future__ import annotations

from .missions_impl.attempts import (
    add_mission_extra_attempt,
    bulk_get_mission_extra_attempts,
    bulk_mission_attempts_today,
    get_mission_daily_limit,
    get_mission_extra_attempts,
    mission_attempts_today,
)
from .missions_impl.drops import award_mission_drops
from .missions_impl.execution import (
    can_retreat,
    finalize_mission_run,
    launch_mission,
    refresh_mission_runs,
    request_retreat,
    schedule_mission_completion,
)
from .missions_impl.loadout import normalize_mission_loadout

__all__ = [
    "add_mission_extra_attempt",
    "award_mission_drops",
    "bulk_get_mission_extra_attempts",
    "bulk_mission_attempts_today",
    "can_retreat",
    "finalize_mission_run",
    "get_mission_daily_limit",
    "get_mission_extra_attempts",
    "launch_mission",
    "mission_attempts_today",
    "normalize_mission_loadout",
    "refresh_mission_runs",
    "request_retreat",
    "schedule_mission_completion",
]
