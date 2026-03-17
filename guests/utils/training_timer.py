from __future__ import annotations

from datetime import datetime

from guests.models import Guest
from guests.training_runtime import ensure_training_timer as _ensure_training_timer_impl
from guests.training_runtime import remaining_training_seconds as _remaining_training_seconds_impl


def ensure_training_timer(guest: Guest, now: datetime | None = None) -> bool:
    """
    确保门客有有效的训练计时器：结算已完成的训练，必要时开启下一次训练。

    Returns True 表示存在未完成的训练计时器，False 表示已达上限或无计时。
    """
    from guests.services.training import ensure_auto_training, finalize_guest_training

    return _ensure_training_timer_impl(
        guest,
        now=now,
        finalize_guest_training_func=finalize_guest_training,
        ensure_auto_training_func=ensure_auto_training,
    )


def remaining_training_seconds(guest: Guest, now: datetime | None = None) -> int:
    """
    计算训练还剩余的秒数（向上取整）；若没有计时器则返回 0。
    """
    return _remaining_training_seconds_impl(guest, now=now)
