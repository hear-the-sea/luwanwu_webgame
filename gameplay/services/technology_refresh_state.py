from __future__ import annotations

from threading import Lock
from typing import Callable

from . import technology_runtime as _technology_runtime

LOCAL_TECH_REFRESH_FALLBACK_MAX_SIZE = 5000
local_tech_refresh_fallback: dict[int, float] = {}
local_tech_refresh_fallback_lock = Lock()


def clear_local_tech_refresh_fallback() -> None:
    with local_tech_refresh_fallback_lock:
        local_tech_refresh_fallback.clear()


def should_skip_tech_refresh_by_local_fallback(
    *,
    manor_id: int,
    min_interval: int,
    monotonic_func: Callable[[], float],
) -> bool:
    return _technology_runtime.should_skip_tech_refresh_by_local_fallback(
        local_tech_refresh_fallback,
        state_lock=local_tech_refresh_fallback_lock,
        max_size=LOCAL_TECH_REFRESH_FALLBACK_MAX_SIZE,
        manor_id=manor_id,
        min_interval=min_interval,
        monotonic_func=monotonic_func,
    )
