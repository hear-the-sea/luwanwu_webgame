"""
门客训练系统服务
"""

from __future__ import annotations

from typing import Dict

from django.db import transaction
from django.utils import timezone

from core.exceptions import (
    GuestError,
    GuestMaxLevelError,
    GuestTrainingInProgressError,
)
from gameplay import services as gameplay_services
from gameplay.models import Manor, ResourceEvent

from ..models import MAX_GUEST_LEVEL, RARITY_SKILL_POINT_GAINS, Guest, GuestStatus, TrainingLog
from ..utils.training_calculator import get_level_up_cost, get_training_duration
from ..utils.training_timer import ensure_training_timer, remaining_training_seconds


def ensure_auto_training(guest: Guest) -> None:
    """
    如果没有训练计划且门客未达到最高等级，则自动开始训练到下一级。
    """
    if guest.level >= MAX_GUEST_LEVEL:
        return
    if guest.training_complete_at:
        return
    target_level = min(MAX_GUEST_LEVEL, guest.level + 1)
    duration = get_training_duration(guest, levels=1)
    guest.training_target_level = target_level
    guest.training_complete_at = timezone.now() + timezone.timedelta(seconds=duration)
    guest.save(update_fields=["training_target_level", "training_complete_at"])
    from guests.tasks import complete_guest_training

    def enqueue_training():
        try:
            complete_guest_training.apply_async(args=[guest.id], countdown=max(0, int(duration)), queue="timer")
        except Exception:
            finalize_guest_training(guest, now=guest.training_complete_at)

    transaction.on_commit(enqueue_training)


def reduce_training_time(manor: Manor, seconds: int) -> Dict[str, int]:
    """
    缩短庄园所有门客的训练时间。多余的时间会顺延到下一级。

    Args:
        manor: 庄园对象
        seconds: 要缩短的秒数

    Returns:
        包含缩短的总时间和影响的门客数量的字典

    Raises:
        GuestError: 所有门客已达等级上限时抛出
    """
    if seconds <= 0:
        return {"time_reduced": 0, "applied_guests": 0}
    guests = list(
        manor.guests.select_related("template").filter(level__lt=MAX_GUEST_LEVEL).order_by("training_complete_at", "id")
    )
    if not guests:
        raise GuestError("所有门客已达等级上限，无法使用该道具。")
    total_reduced = 0
    applied = 0
    now = timezone.now()
    remaining_seconds = int(seconds)

    for guest in guests:
        if not ensure_training_timer(guest, now=now):
            continue
        while remaining_seconds > 0 and guest.training_complete_at and guest.level < MAX_GUEST_LEVEL:
            remaining = remaining_training_seconds(guest, now=timezone.now())
            if remaining <= 0:
                finalize_guest_training(guest)
                guest.refresh_from_db()
                if guest.level >= MAX_GUEST_LEVEL:
                    break
                continue
            if remaining_seconds >= remaining:
                total_reduced += remaining
                remaining_seconds -= remaining
                finalize_guest_training(guest)
                guest.refresh_from_db()
                applied += 1
                if guest.level >= MAX_GUEST_LEVEL:
                    break
                if not guest.training_complete_at:
                    ensure_auto_training(guest)
                    guest.refresh_from_db()
            else:
                guest.training_complete_at = guest.training_complete_at - timezone.timedelta(seconds=remaining_seconds)
                guest.save(update_fields=["training_complete_at"])
                total_reduced += remaining_seconds
                remaining_seconds = 0
                applied += 1
        if remaining_seconds <= 0:
            break
    return {"time_reduced": total_reduced, "applied_guests": applied}


def reduce_training_time_for_guest(guest: Guest, seconds: int) -> Dict[str, int]:
    """
    缩短单个门客的训练时间。多余的时间继续用于后续等级。

    Args:
        guest: 门客对象
        seconds: 要缩短的秒数

    Returns:
        包含缩短的总时间、影响的等级数和下次完成时间的字典

    Raises:
        GuestMaxLevelError: 门客已达等级上限时抛出
    """
    if seconds <= 0:
        return {"time_reduced": 0, "applied_levels": 0}
    now = timezone.now()
    if not ensure_training_timer(guest, now=now):
        if guest.level >= MAX_GUEST_LEVEL:
            raise GuestMaxLevelError(guest, max_level=MAX_GUEST_LEVEL)

    remaining_seconds = int(seconds)
    total_reduced = 0
    levels_applied = 0

    while remaining_seconds > 0 and guest.level < MAX_GUEST_LEVEL:
        if not ensure_training_timer(guest, now=now):
            break
        remaining = remaining_training_seconds(guest, now=timezone.now())
        if remaining <= 0:
            if finalize_guest_training(guest):
                levels_applied += 1
                guest.refresh_from_db()
            else:
                break
            continue

        consume = min(remaining_seconds, remaining)
        total_reduced += consume
        remaining_seconds -= consume

        if consume >= remaining:
            # 完成当前等级并进入下一级
            if finalize_guest_training(guest, now=guest.training_complete_at):
                levels_applied += 1
                guest.refresh_from_db()
        else:
            guest.training_complete_at = guest.training_complete_at - timezone.timedelta(seconds=consume)
            guest.save(update_fields=["training_complete_at"])

    # 确保训练计时器存在并重新调度任务
    finalize_guest_training(guest)
    if guest.level < MAX_GUEST_LEVEL and not guest.training_complete_at:
        ensure_auto_training(guest)
        guest.refresh_from_db()
    if guest.training_complete_at:
        from guests.tasks import complete_guest_training

        countdown = max(0, int((guest.training_complete_at - timezone.now()).total_seconds()))

        def enqueue_training():
            try:
                complete_guest_training.apply_async(args=[guest.id], countdown=countdown, queue="timer")
            except Exception:
                finalize_guest_training(guest, now=guest.training_complete_at)

        transaction.on_commit(enqueue_training)
    return {
        "time_reduced": total_reduced,
        "applied_levels": levels_applied,
        "next_eta": guest.training_complete_at,
    }


@transaction.atomic
def train_guest(guest: Guest, levels: int = 1) -> Guest:
    """
    开始培养门客，消耗资源并设置训练计时器。

    Args:
        guest: 门客对象
        levels: 要提升的等级数（默认为1）

    Returns:
        更新后的门客对象

    Raises:
        GuestMaxLevelError: 门客已达上限时抛出
        GuestTrainingInProgressError: 门客已在训练中时抛出
    """
    if not getattr(guest, "pk", None):
        raise GuestError("门客未保存，无法训练")

    locked_guest = (
        Guest.objects.select_for_update()
        .select_related("manor", "template")
        .get(pk=guest.pk)
    )
    if locked_guest.level >= MAX_GUEST_LEVEL:
        raise GuestMaxLevelError(locked_guest, max_level=MAX_GUEST_LEVEL)
    if locked_guest.training_complete_at:
        raise GuestTrainingInProgressError(locked_guest)
    if locked_guest.level + levels > MAX_GUEST_LEVEL:
        levels = MAX_GUEST_LEVEL - locked_guest.level
    manor = locked_guest.manor
    cost = get_level_up_cost(locked_guest, levels)
    gameplay_services.spend_resources(
        manor,
        cost,
        note=f"培养 {guest.template.name}",
        reason=ResourceEvent.Reason.TRAINING_COST,
    )
    duration = get_training_duration(locked_guest, levels)
    locked_guest.training_target_level = locked_guest.level + levels
    locked_guest.training_complete_at = timezone.now() + timezone.timedelta(seconds=duration)
    locked_guest.save(update_fields=["training_target_level", "training_complete_at"])
    TrainingLog.objects.create(manor=manor, guest=locked_guest, delta_level=levels, resource_cost=cost)
    from guests.tasks import complete_guest_training

    # Celery 不可用时直接完成训练，确保调用方立即看到等级变更（测试/开发环境友好）。
    def enqueue_training():
        try:
            complete_guest_training.apply_async(
                args=[locked_guest.id],
                countdown=max(0, int(duration)),
                queue="timer",
            )
        except Exception:
            finalize_guest_training(locked_guest, now=locked_guest.training_complete_at)

    transaction.on_commit(enqueue_training)
    return locked_guest


def finalize_guest_training(guest: Guest, now=None) -> bool:
    """
    完成门客训练，提升等级并随机增加属性。

    Args:
        guest: 门客对象
        now: 当前时间（可选）

    Returns:
        是否成功完成训练
    """
    from guests.utils.attribute_growth import (
        allocate_level_up_attributes,
        apply_attribute_growth,
    )

    now = now or timezone.now()
    if not getattr(guest, "pk", None):
        return False

    with transaction.atomic():
        locked_guest = (
            Guest.objects.select_for_update()
            .select_related("manor", "template")
            .get(pk=guest.pk)
        )
        if not locked_guest.training_complete_at or locked_guest.training_complete_at > now:
            return False

        target_level = max(locked_guest.level, locked_guest.training_target_level or locked_guest.level)
        levels_gained = max(0, target_level - locked_guest.level)

        # 随机分配属性增长
        if levels_gained > 0:
            allocation = allocate_level_up_attributes(locked_guest, levels=levels_gained)
            apply_attribute_growth(locked_guest, allocation)

        # 更新等级和属性点
        locked_guest.level = min(target_level, MAX_GUEST_LEVEL)
        locked_guest.training_complete_at = None
        locked_guest.training_target_level = 0

        per_level_points = RARITY_SKILL_POINT_GAINS.get(locked_guest.rarity, 1)
        locked_guest.attribute_points += per_level_points * levels_gained
        locked_guest.experience = 0
        locked_guest.current_hp = locked_guest.max_hp

        # 训练完成恢复满血时，解除重伤状态
        if locked_guest.status == GuestStatus.INJURED:
            locked_guest.status = GuestStatus.IDLE

        locked_guest.save(
            update_fields=[
                "level",
                "force",           # 新增：属性会改变
                "intellect",       # 新增：属性会改变
                "defense_stat",    # 新增：属性会改变
                "agility",         # 新增：属性会改变
                "training_complete_at",
                "training_target_level",
                "attribute_points",
                "experience",
                "current_hp",
                "status",
            ]
        )

        if locked_guest.level < MAX_GUEST_LEVEL:
            ensure_auto_training(locked_guest)

    return True
