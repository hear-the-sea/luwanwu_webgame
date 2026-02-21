from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from django.conf import settings


@dataclass(frozen=True)
class TimeScale:
    """
    全局时间流速配置（倍率）。

    - 1.0：默认速度
    - 100：所有计时类行为加速 100 倍（耗时 / 100）
    """

    multiplier: float = 1.0


def get_time_scale() -> TimeScale:
    raw: Any = getattr(settings, "GAME_TIME_MULTIPLIER", 1.0)
    try:
        multiplier = float(raw)
    except (TypeError, ValueError):
        multiplier = 1.0

    if not math.isfinite(multiplier) or multiplier <= 0:
        multiplier = 1.0

    return TimeScale(multiplier=multiplier)


def scale_duration(seconds: float | int, minimum: int = 1) -> int:
    """
    将“游戏内耗时（秒）”映射为“真实耗时（秒）”。

    示例：multiplier=100 时，100 秒游戏耗时 → 1 秒真实耗时。
    """
    if seconds <= 0:
        return 0
    multiplier = get_time_scale().multiplier
    scaled = seconds / multiplier
    return max(minimum, int(scaled))


def scale_value(value: float | int) -> float:
    """
    将“每秒进度/增量”按时间倍率放大（用于按真实时间累计的系统，如离线产出）。
    """
    multiplier = get_time_scale().multiplier
    return float(value) * multiplier
