"""任务管理服务（向后兼容门面）。

`gameplay.services.missions` 历史上是一个 800+ 行的大模块。
为提高可维护性，核心实现已迁移到 `gameplay.services.missions/*` 目录。

此文件保留旧的 import API，`gameplay/services/missions.py` 会 re-export。
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
