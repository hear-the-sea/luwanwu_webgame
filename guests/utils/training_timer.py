from __future__ import annotations

import math

from django.utils import timezone

from guests.models import MAX_GUEST_LEVEL, Guest


def ensure_training_timer(guest: Guest, now: timezone.datetime | None = None) -> bool:
    """
    确保门客有有效的训练计时器：结算已完成的训练，必要时开启下一次训练。

    Returns True 表示存在未完成的训练计时器，False 表示已达上限或无计时。
    """
    now = now or timezone.now()
    # 延迟导入以避免循环依赖（避免加载 guests.services 的大门面）
    from guests.services.training import ensure_auto_training, finalize_guest_training

    finalize_guest_training(guest, now=now)
    if guest.level >= MAX_GUEST_LEVEL:
        return False
    if not guest.training_complete_at:
        ensure_auto_training(guest)
        guest.refresh_from_db()
    return bool(guest.training_complete_at)


def remaining_training_seconds(guest: Guest, now: timezone.datetime | None = None) -> int:
    """
    计算训练还剩余的秒数（向上取整）；若没有计时器则返回 0。
    """
    if not guest.training_complete_at:
        return 0
    now = now or timezone.now()
    remaining = (guest.training_complete_at - now).total_seconds()
    if remaining <= 0:
        return 0
    return int(math.ceil(remaining))
