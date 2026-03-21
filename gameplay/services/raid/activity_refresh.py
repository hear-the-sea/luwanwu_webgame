from __future__ import annotations

from typing import Any, Callable

from .combat import refresh_raid_runs
from .scout import refresh_scout_records


def refresh_raid_activity(
    manor: Any,
    *,
    prefer_async: bool = True,
    refresh_scout_records_func: Callable[..., None] = refresh_scout_records,
    refresh_raid_runs_func: Callable[..., None] = refresh_raid_runs,
) -> None:
    """显式触发侦察/踢馆补偿刷新。"""
    refresh_scout_records_func(manor, prefer_async=prefer_async)
    refresh_raid_runs_func(manor, prefer_async=prefer_async)
