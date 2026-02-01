"""
资源管理服务
"""

from __future__ import annotations

import logging
from typing import Dict

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.utils.time_scale import scale_value
from ..models import Manor, ResourceEvent, ResourceType
from ..utils.resource_calculator import RESOURCE_FIELDS, get_hourly_rates

logger = logging.getLogger(__name__)


def spend_resources_locked(
    manor: Manor, cost: Dict[str, int], note: str, reason: str = ResourceEvent.Reason.UPGRADE_COST
) -> None:
    """
    消耗庄园资源（假设调用方已在 transaction.atomic 中完成所需的并发控制）。

    该函数不会创建新的事务块，也不会额外对 Manor 行加锁；适用于上层服务函数已经
    `select_for_update()` 锁定 manor 行的场景，避免重复锁与嵌套事务的冗余开销。
    """
    if not cost:
        return
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("spend_resources_locked must be called inside transaction.atomic()")

    filters = {f"{key}__gte": value for key, value in cost.items()}
    updates = {key: F(key) - value for key, value in cost.items()}
    updated = Manor.objects.filter(pk=manor.pk, **filters).update(**updates)
    if not updated:
        raise ValueError("资源不足")

    manor.refresh_from_db(fields=RESOURCE_FIELDS)
    negative = {key: -val for key, val in cost.items()}
    log_resource_gain(manor, negative, reason, note)


def grant_resources_locked(
    manor: Manor, rewards: Dict[str, int], note: str, reason: str = ResourceEvent.Reason.TASK_REWARD
) -> Dict[str, int]:
    """
    发放资源奖励给庄园（假设调用方已在 transaction.atomic 中持有 manor 行锁）。

    该函数不会创建新的事务块，也不会额外对 Manor 行加锁；适用于上层服务函数已经
    `select_for_update()` 锁定 manor 行的场景，避免重复锁与嵌套事务的冗余开销。
    """
    if not rewards:
        return {}
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("grant_resources_locked must be called inside transaction.atomic()")

    credited: Dict[str, int] = {}
    for resource, amount in rewards.items():
        if amount <= 0:
            continue
        # 使用各资源对应的容量上限
        if resource == ResourceType.SILVER:
            capacity = manor.silver_capacity
        elif resource == ResourceType.GRAIN:
            capacity = manor.grain_capacity
        else:
            # 代码质量修复：记录未知资源类型，便于排查配置错误
            logger.warning(
                f"未知资源类型被跳过: {resource}={amount}",
                extra={"manor_id": manor.id, "resource": resource, "amount": amount}
            )
            continue  # 未知资源类型跳过

        current_value = getattr(manor, resource, 0)
        new_value = min(capacity, current_value + amount)
        added = max(0, new_value - current_value)
        if added <= 0:
            continue
        setattr(manor, resource, new_value)
        credited[resource] = added

    if credited:
        manor.save(update_fields=list(credited.keys()))
        log_resource_gain(manor, credited, reason, note)
    return credited


def sync_resource_production(manor: Manor) -> None:
    """
    同步庄园资源产出，根据离线时间计算并发放资源。

    Uses row-level locking to prevent concurrent race conditions that could
    lead to duplicate resource awards. The manor parameter will be refreshed
    to reflect the latest database state before returning.

    Note: resource_updated_at is only advanced when elapsed_seconds > 0 to
    prevent unnecessary database writes on repeated zero-elapsed calls.

    Args:
        manor: 庄园对象（会被刷新以反映最新状态）
    """
    now = timezone.now()
    min_interval = getattr(settings, "RESOURCE_SYNC_MIN_INTERVAL_SECONDS", 0)
    if min_interval > 0:
        elapsed_hint = (now - manor.resource_updated_at).total_seconds()
        if elapsed_hint < min_interval:
            return

    with transaction.atomic():
        # Lock the manor row to prevent concurrent production syncs
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)

        # Calculate elapsed time from the locked manor's timestamp
        elapsed_seconds = (now - locked_manor.resource_updated_at).total_seconds()
        if elapsed_seconds > 0:
            elapsed_seconds = scale_value(elapsed_seconds)
            hourly_rates = get_hourly_rates(locked_manor)
            produced = {}

            for resource in RESOURCE_FIELDS:
                per_hour = hourly_rates.get(resource, 0)
                gain = int(per_hour * (elapsed_seconds / 3600))
                if gain <= 0:
                    continue

                current_value = getattr(locked_manor, resource)

                # 使用各资源对应的容量上限
                if resource == ResourceType.SILVER:
                    capacity = locked_manor.silver_capacity
                elif resource == ResourceType.GRAIN:
                    capacity = locked_manor.grain_capacity
                else:
                    continue  # 未知资源类型跳过

                new_value = min(capacity, current_value + gain)
                added = max(0, new_value - current_value)

                if added > 0:
                    setattr(locked_manor, resource, new_value)
                    produced[resource] = added

            # Update timestamp even if no resources produced (prevents repeated checks)
            locked_manor.resource_updated_at = now

            # Only update fields that changed plus timestamp
            update_fields = list(produced.keys()) + ["resource_updated_at"]
            locked_manor.save(update_fields=update_fields)

            # Log resource gain if any resources were produced
            if produced:
                log_resource_gain(locked_manor, produced, ResourceEvent.Reason.PRODUCE, note="离线产出")

    # Always refresh the original manor object to reflect database state
    manor.refresh_from_db(fields=RESOURCE_FIELDS + ["resource_updated_at"])


def log_resource_gain(manor: Manor, payload: Dict[str, int], reason: str, note: str = "") -> None:
    """
    记录资源变化日志。

    Args:
        manor: 庄园对象
        payload: 资源变化字典 {resource_type: delta}
        reason: 变化原因
        note: 备注信息
    """
    events = [
        ResourceEvent(manor=manor, resource_type=resource, delta=delta, reason=reason, note=note)
        for resource, delta in payload.items()
        if delta
    ]
    if events:
        ResourceEvent.objects.bulk_create(events)


def spend_resources(
    manor: Manor, cost: Dict[str, int], note: str, reason: str = ResourceEvent.Reason.UPGRADE_COST
) -> None:
    """
    消耗庄园资源。

    Args:
        manor: 庄园对象
        cost: 资源消耗字典 {resource_type: amount}
        note: 消耗说明
        reason: 消耗原因

    Raises:
        ValueError: 资源不足时抛出
    """
    if not cost:
        return

    with transaction.atomic():
        Manor.objects.select_for_update().filter(pk=manor.pk).exists()
        spend_resources_locked(manor, cost, note=note, reason=reason)


def grant_resources(
    manor: Manor, rewards: Dict[str, int], note: str, reason: str = ResourceEvent.Reason.TASK_REWARD
) -> Dict[str, int]:
    """
    发放资源奖励给庄园。

    Uses row-level locking to ensure thread-safe updates and respects
    storage capacity limits. Rewards beyond capacity are ignored.

    Args:
        manor: 庄园对象
        rewards: 资源奖励字典 {resource_type: amount}
        note: 奖励说明
        reason: 奖励原因

    Returns:
        实际入账资源字典 {resource_type: credited_amount}
    """
    if not rewards:
        return {}

    credited: Dict[str, int] = {}

    with transaction.atomic():
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
        credited = grant_resources_locked(locked_manor, rewards, note=note, reason=reason)

    if credited:
        manor.refresh_from_db(fields=RESOURCE_FIELDS)
    return credited
