from __future__ import annotations

from gameplay.models import ArenaEntry, Manor

from .helpers import today_bounds, today_local_date


def sync_daily_participation_counter_locked(locked_manor: Manor, *, now=None) -> int:
    """
    同步庄园侧的竞技场日计数。

    说明：
    - 计数以 Manor 字段为准，避免赛事记录被清理后次数“回收”。
    - 当天首次访问且字段未初始化时，回填为当日现存 ArenaEntry 数量，兼容历史数据。
    """
    today = today_local_date(now=now)
    if locked_manor.arena_participation_date == today:
        return max(0, int(locked_manor.arena_participations_today or 0))

    day_start, day_end = today_bounds(now=now)
    today_count = ArenaEntry.objects.filter(manor=locked_manor, joined_at__gte=day_start, joined_at__lt=day_end).count()
    locked_manor.arena_participation_date = today
    locked_manor.arena_participations_today = max(0, int(today_count))
    locked_manor.save(update_fields=["arena_participation_date", "arena_participations_today"])
    return locked_manor.arena_participations_today


def update_daily_participation_counter_locked(locked_manor: Manor, *, delta: int, now=None) -> int:
    current = sync_daily_participation_counter_locked(locked_manor, now=now)
    updated = max(0, int(current) + int(delta))
    locked_manor.arena_participation_date = today_local_date(now=now)
    locked_manor.arena_participations_today = updated
    locked_manor.save(update_fields=["arena_participation_date", "arena_participations_today"])
    return updated
