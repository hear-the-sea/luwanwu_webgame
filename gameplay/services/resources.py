"""
资源管理服务
"""

from __future__ import annotations

import logging
from typing import Dict, Tuple

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.utils.time_scale import scale_value

from ..models import Manor, ResourceEvent, ResourceType
from ..utils.resource_calculator import RESOURCE_FIELDS, get_hourly_rates, get_personnel_grain_cost_per_hour

logger = logging.getLogger(__name__)


def _sync_warehouse_grain_item_locked(manor: Manor) -> None:
    # Delay import to avoid circular dependency:
    # resources -> inventory package -> inventory.use -> resources.
    from .inventory.core import sync_warehouse_grain_item_locked

    sync_warehouse_grain_item_locked(manor)


def _get_resource_capacity(manor: Manor, resource: str) -> Tuple[int, bool]:
    """
    获取指定资源的容量上限。

    DRY 修复：提取重复的容量判断逻辑为辅助函数。

    Args:
        manor: 庄园对象（应该是锁定后的对象以保证事务一致性）
        resource: 资源类型

    Returns:
        (容量值, 是否为有效资源类型)
    """
    if resource == ResourceType.SILVER:
        return manor.silver_capacity, True
    elif resource == ResourceType.GRAIN:
        return manor.grain_capacity, True
    else:
        return 0, False


def _handle_unknown_resource(manor: Manor, resource: str, amount: int) -> None:
    if settings.DEBUG:
        raise ValueError(f"未知资源类型: {resource}")
    logger.error(
        "未知资源类型被跳过: %s=%s",
        resource,
        amount,
        extra={"manor_id": manor.id, "resource": resource, "amount": amount},
    )


def _credit_resource(manor: Manor, resource: str, amount: int) -> Tuple[int, int] | None:
    if amount <= 0:
        return None

    capacity, is_valid = _get_resource_capacity(manor, resource)
    if not is_valid:
        _handle_unknown_resource(manor, resource, amount)
        return None

    current_value = getattr(manor, resource, 0)
    new_value = min(capacity, current_value + amount)
    added = max(0, new_value - current_value)
    overflowed = amount - added
    if added > 0:
        setattr(manor, resource, new_value)
    return added, overflowed


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
    if int(cost.get(ResourceType.GRAIN, 0) or 0) > 0:
        _sync_warehouse_grain_item_locked(manor)
    negative = {key: -val for key, val in cost.items()}
    log_resource_gain(manor, negative, reason, note)


def grant_resources_locked(
    manor: Manor, rewards: Dict[str, int], note: str, reason: str = ResourceEvent.Reason.TASK_REWARD
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    发放资源奖励给庄园（假设调用方已在 transaction.atomic 中持有 manor 行锁）。

    该函数不会创建新的事务块，也不会额外对 Manor 行加锁；适用于上层服务函数已经
    `select_for_update()` 锁定 manor 行的场景，避免重复锁与嵌套事务的冗余开销。

    Returns:
        (credited, overflow) - 实际入账资源和溢出资源字典
    """
    if not rewards:
        return {}, {}
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("grant_resources_locked must be called inside transaction.atomic()")

    credited: Dict[str, int] = {}
    overflow: Dict[str, int] = {}

    for resource, amount in rewards.items():
        credit_result = _credit_resource(manor, resource, amount)
        if credit_result is None:
            continue

        added, overflowed = credit_result
        if added <= 0:
            overflow[resource] = amount
            continue

        credited[resource] = added
        if overflowed > 0:
            overflow[resource] = overflowed

    if credited:
        manor.save(update_fields=list(credited.keys()))
        if int(credited.get(ResourceType.GRAIN, 0) or 0) > 0:
            _sync_warehouse_grain_item_locked(manor)
        log_resource_gain(manor, credited, reason, note)

    # 记录溢出情况便于调试
    if overflow:
        logger.debug(
            "资源溢出被丢弃: %s",
            overflow,
            extra={"manor_id": manor.id, "overflow": overflow},
        )

    return credited, overflow


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
            personnel_grain_cost = get_personnel_grain_cost_per_hour(locked_manor)
            hourly_rates[ResourceType.GRAIN] = hourly_rates.get(ResourceType.GRAIN, 0) - personnel_grain_cost
            produced = {}

            for resource in RESOURCE_FIELDS:
                per_hour = hourly_rates.get(resource, 0)
                delta = int(per_hour * (elapsed_seconds / 3600))
                if delta == 0:
                    continue

                current_value = getattr(locked_manor, resource)

                # DRY 修复：使用辅助函数获取容量（在锁内调用保证事务一致性）
                capacity, is_valid = _get_resource_capacity(locked_manor, resource)
                if not is_valid:
                    continue

                if delta > 0:
                    new_value = min(capacity, current_value + delta)
                else:
                    new_value = max(0, current_value + delta)
                actual_delta = new_value - current_value

                if actual_delta != 0:
                    setattr(locked_manor, resource, new_value)
                    produced[resource] = actual_delta

            # Update timestamp even if no resources produced (prevents repeated checks)
            locked_manor.resource_updated_at = now

            # Only update fields that changed plus timestamp
            update_fields = list(produced.keys()) + ["resource_updated_at"]
            locked_manor.save(update_fields=update_fields)
            if int(produced.get(ResourceType.GRAIN, 0) or 0) != 0:
                _sync_warehouse_grain_item_locked(locked_manor)

            # Log resource gain if any resources were produced
            if produced:
                log_resource_gain(
                    locked_manor,
                    {str(k): int(v) for k, v in produced.items()},
                    ResourceEvent.Reason.PRODUCE,
                    note="离线产出",
                )

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
        # 安全修复：正确获取锁定后的 manor 对象并传递给 spend_resources_locked
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
        spend_resources_locked(locked_manor, cost, note=note, reason=reason)

    # 刷新原始 manor 对象以反映最新状态
    manor.refresh_from_db(fields=RESOURCE_FIELDS)


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

    with transaction.atomic():
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
        # 修复：正确解构 grant_resources_locked 的返回值
        credited, _overflow = grant_resources_locked(locked_manor, rewards, note=note, reason=reason)

    if credited:
        manor.refresh_from_db(fields=RESOURCE_FIELDS)
    return credited
