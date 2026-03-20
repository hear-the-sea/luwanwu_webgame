"""
Item usage logic (warehouse-usable items + guest-target items).

This module depends on the core inventory operations in `core.py`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from django.db import transaction

from core.exceptions import (
    GuestAlreadyOwnedError,
    GuestCapacityFullError,
    ItemNotConfiguredError,
    ItemNotFoundError,
    ItemNotUsableError,
)
from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from gameplay.services.resources import grant_resources, grant_resources_locked

from .core import add_item_to_inventory, consume_inventory_item_for_manor_locked, consume_inventory_item_locked
from .guest_items import (  # noqa: F401
    use_guest_rarity_upgrade_item,
    use_guest_rebirth_card,
    use_soul_container,
    use_xidianka,
    use_xisuidan,
)
from .random_source import inventory_random

logger = logging.getLogger(__name__)

ItemEffectHandler = Callable[[InventoryItem], dict[str, Any]]

# 不在仓库使用的物品提示信息
NON_WAREHOUSE_MESSAGES: dict[str, str] = {
    ItemTemplate.EffectType.SKILL_BOOK: "技能书请在门客详情页为指定门客使用",
    ItemTemplate.EffectType.EXPERIENCE_ITEM: "经验道具请在门客详情页为指定门客使用",
    ItemTemplate.EffectType.MEDICINE: "药品道具请在门客详情页为指定门客使用",
}


def _collect_weighted_template_choices(choices: list) -> tuple[list[str], list[int]]:
    template_keys: List[str] = []
    weights: List[int] = []
    for entry in choices:
        if not isinstance(entry, dict):
            continue
        template_key = entry.get("template_key")
        if not template_key:
            continue
        try:
            weight = int(entry.get("weight", 0) or 0)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        template_keys.append(str(template_key))
        weights.append(weight)
    return template_keys, weights


def _weighted_choose_template_key(template_keys: List[str], weights: List[int]) -> str:
    total_weight = sum(weights)
    roll = inventory_random.random() * total_weight
    chosen_key = template_keys[-1]
    cumulative = 0
    for template_key, weight in zip(template_keys, weights):
        cumulative += weight
        if roll < cumulative:
            chosen_key = template_key
            break
    return chosen_key


def _ensure_guest_capacity(manor: Manor) -> None:
    if manor.guests.count() >= manor.guest_capacity:
        raise GuestCapacityFullError()


def _consume_required_items_locked(manor: Manor, payload: dict[str, Any]) -> None:
    required_items = payload.get("required_items") or {}
    if not isinstance(required_items, dict):
        return

    for item_key, raw_amount in required_items.items():
        normalized_key = str(item_key or "").strip()
        if not normalized_key:
            continue
        try:
            amount = int(raw_amount)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            continue
        consume_inventory_item_for_manor_locked(manor, normalized_key, amount)


def _grant_item_resources(manor: Manor, payload: dict[str, int], note: str) -> dict[str, int]:
    if transaction.get_connection().in_atomic_block:
        credited, _overflow = grant_resources_locked(
            manor,
            payload,
            note,
            ResourceEvent.Reason.ITEM_USE,
            sync_production=False,
        )
        return credited
    return grant_resources(
        manor,
        payload,
        note,
        ResourceEvent.Reason.ITEM_USE,
        sync_production=False,
    )


def _normalize_probability(value: Any) -> float:
    """Normalize probability config to [0, 1]. Supports 0.1 or 10 (percent)."""
    try:
        prob = float(value)
    except (TypeError, ValueError):
        return 0.0

    if prob > 1 and prob <= 100:
        prob = prob / 100.0
    return max(0.0, min(1.0, prob))


def _apply_resource_pack(item: InventoryItem) -> Dict[str, Any]:
    """使用资源包，发放资源奖励。"""
    payload = item.template.effect_payload or {}
    if not payload:
        raise ItemNotConfiguredError()
    granted_resources = _grant_item_resources(item.manor, payload, item.template.name)
    parts = [f"{key}+{value}" for key, value in granted_resources.items()]
    return {
        **granted_resources,
        "_message": f"获得 {'、'.join(parts)}",
    }


def _apply_peace_shield(item: InventoryItem) -> Dict[str, Any]:
    """使用免战牌，激活保护状态。"""
    from gameplay.services.raid import activate_peace_shield

    payload = item.template.effect_payload or {}
    duration = payload.get("duration")
    if not duration:
        raise ItemNotConfiguredError()

    manor = item.manor
    activate_peace_shield(manor, duration)
    hours = duration // 3600
    return {
        "duration_seconds": duration,
        "duration_hours": hours,
        "_message": f"获得 {hours}小时 免战保护",
    }


def _apply_guest_summon(item: InventoryItem) -> Dict[str, Any]:
    """
    使用门客召唤卡：按权重随机获得一个门客模板并直接加入聚贤庄。
    """
    payload = item.template.effect_payload or {}
    choices = payload.get("choices") or []
    if not isinstance(choices, list):
        raise ItemNotConfiguredError()

    template_keys, weights = _collect_weighted_template_choices(choices)
    if not template_keys:
        raise ItemNotConfiguredError()

    chosen_key = _weighted_choose_template_key(template_keys, weights)

    manor = item.manor
    _ensure_guest_capacity(manor)

    from guests.models import GuestTemplate
    from guests.services.recruitment_guests import create_guest_from_template

    template = GuestTemplate.objects.filter(key=chosen_key).first()
    if not template:
        raise ItemNotConfiguredError(f"门客模板不存在: {chosen_key}")

    exclusive_template_keys = payload.get("exclusive_template_keys") or []
    if isinstance(exclusive_template_keys, list):
        normalized_exclusive_keys = [str(key).strip() for key in exclusive_template_keys if str(key).strip()]
        if normalized_exclusive_keys and manor.guests.filter(template__key__in=normalized_exclusive_keys).exists():
            raise GuestAlreadyOwnedError(template)

    _consume_required_items_locked(manor, payload)

    guest = create_guest_from_template(
        manor=manor,
        template=template,
        rng=inventory_random.Random(),
    )

    rarity_display = template.get_rarity_display()
    return {
        "获得门客": guest.display_name,
        "稀有度": rarity_display,
        "_message": f"获得门客 {guest.display_name}（{rarity_display}）",
    }


def _apply_tool(item: InventoryItem) -> Dict[str, Any]:
    """
    使用道具类物品（统一 effect_type=tool）。
    """
    payload = item.template.effect_payload or {}
    if payload.get("action") == "summon_guest":
        return _apply_guest_summon(item)
    if payload.get("action") == "rebirth_guest":
        # 门客重生卡需要选择目标门客，抛出提示让前端引导选择
        raise ItemNotUsableError(item.template.name, message="请选择要重生的门客")
    if payload.get("action") == "upgrade_guest_rarity":
        raise ItemNotUsableError(item.template.name, message="请选择要升阶的门客")
    if payload.get("action") == "soul_fusion":
        raise ItemNotUsableError(item.template.name, message="请选择要融合的门客")
    key = item.template.key or ""
    if key.startswith("peace_shield_"):
        return _apply_peace_shield(item)
    raise ItemNotUsableError(item.template.name, message="未知的道具效果")


def _apply_loot_box(item: InventoryItem) -> Dict[str, Any]:
    """使用宝箱类物品，按配置发放多种奖励。"""
    payload = item.template.effect_payload or {}
    if not payload:
        raise ItemNotConfiguredError()

    manor = item.manor
    rewards: List[str] = []

    # 1. 固定资源掉落（可选）
    resources = payload.get("resources") or {}
    if resources:
        result = _grant_item_resources(manor, resources, item.template.name)
        parts = [f"{k}+{v}" for k, v in result.items()]
        rewards.append("资源：" + "、".join(parts))

    # 2. 随机银两（可选）
    silver_min_raw = payload.get("silver_min")
    silver_max_raw = payload.get("silver_max")
    if silver_min_raw is not None or silver_max_raw is not None:
        try:
            silver_min = int(silver_min_raw if silver_min_raw is not None else 0)
            silver_max = int(silver_max_raw if silver_max_raw is not None else silver_min)
        except (TypeError, ValueError):
            raise ItemNotConfiguredError()

        silver_min = max(0, silver_min)
        silver_max = max(0, silver_max)
        if silver_max < silver_min:
            silver_min, silver_max = silver_max, silver_min

        rolled_silver = inventory_random.randint(silver_min, silver_max)
        if rolled_silver > 0:
            silver_result = _grant_item_resources(manor, {"silver": rolled_silver}, item.template.name)
            granted_silver = int(silver_result.get("silver", 0) or 0)
            if granted_silver > 0:
                rewards.append(f"银两+{granted_silver}")

    # 3. 装备掉落（概率，随机一件）
    gear_keys = payload.get("gear_keys") or []
    gear_chance = _normalize_probability(payload.get("gear_chance", 0))
    skipped_bonus_items: List[str] = []
    if gear_chance > 0 and gear_keys and inventory_random.random() < gear_chance:
        from guests.models import GearTemplate
        from guests.services.equipment import give_gear

        gear_key = inventory_random.choice(gear_keys)
        gear_template = GearTemplate.objects.filter(key=gear_key).first()
        if not gear_template:
            skipped_bonus_items.append(gear_key)
        else:
            give_gear(manor, gear_template)
            rewards.append(f"装备【{gear_template.name}】")

    # 4. 技能书掉落（概率，随机一本）
    skill_book_chance = _normalize_probability(payload.get("skill_book_chance", 0))
    skill_book_keys = payload.get("skill_book_keys", [])
    if skill_book_chance > 0 and skill_book_keys and inventory_random.random() < skill_book_chance:
        book_key = inventory_random.choice(skill_book_keys)
        try:
            add_item_to_inventory(manor, book_key, 1)
            book_template = ItemTemplate.objects.filter(key=book_key).first()
            book_name = book_template.name if book_template else book_key
            rewards.append(f"技能书【{book_name}】")
        except ItemNotFoundError as exc:
            logger.warning(
                "loot box bonus item grant skipped: manor_id=%s loot_box_item_id=%s bonus_item_key=%s error=%s",
                manor.id,
                item.id,
                book_key,
                exc,
            )
            skipped_bonus_items.append(book_key)

    reward_text = "、".join(rewards) if rewards else "空"
    return {
        "rewards": rewards,
        "skipped_bonus_items": skipped_bonus_items,
        "_message": f"打开宝箱获得：{reward_text}",
    }


ITEM_EFFECT_HANDLERS: dict[str, ItemEffectHandler] = {
    ItemTemplate.EffectType.RESOURCE_PACK: _apply_resource_pack,
    ItemTemplate.EffectType.TOOL: _apply_tool,
    ItemTemplate.EffectType.LOOT_BOX: _apply_loot_box,
}


@transaction.atomic
def use_inventory_item(item: InventoryItem, manor: Manor | None = None) -> Dict[str, Any]:
    """
    使用背包物品（仓库可用）。

    Args:
        item: 要使用的物品实例
        manor: 庄园实例（可选，用于安全校验）

    Returns:
        使用效果摘要字典

    Raises:
        ItemNotFoundError: 物品不存在或不属于指定庄园
        InsufficientStockError: 物品数量不足
        ItemNotUsableError: 物品不可用
    """
    from core.exceptions import InsufficientStockError

    if not item.pk:
        raise ItemNotFoundError()

    # 死锁预防：统一锁顺序 Manor -> InventoryItem
    # 商店服务是先锁 Manor 后锁 Item，此处必须保持一致
    target_manor_id = manor.pk if manor else item.manor_id
    if target_manor_id:
        Manor.objects.select_for_update().get(pk=target_manor_id)

    # 构建查询条件
    query_filter: dict[str, object] = {"pk": item.pk}
    if manor is not None:
        # 如果提供了manor，校验物品归属
        query_filter["manor"] = manor

    locked_item = (
        InventoryItem.objects.select_for_update().select_related("template", "manor").filter(**query_filter).first()
    )
    if not locked_item:
        if manor is not None:
            raise ItemNotFoundError("物品不存在或不属于您的庄园")
        raise InsufficientStockError(item.template.name, 1, 0)
    if locked_item.quantity <= 0:
        raise InsufficientStockError(locked_item.template.name, 1, locked_item.quantity)

    template = locked_item.template
    if not template.is_usable:
        raise ItemNotUsableError(template.name, "not_warehouse_usable")

    handler = ITEM_EFFECT_HANDLERS.get(template.effect_type)
    if handler:
        effect_summary = handler(locked_item)
    else:
        effect_type = template.effect_type or ""
        if effect_type.startswith("equip_"):
            raise ItemNotUsableError(template.name, "equip_in_guest_detail")
        message = NON_WAREHOUSE_MESSAGES.get(effect_type)
        if message:
            raise ItemNotUsableError(template.name, effect_type)
        raise ItemNotUsableError(template.name, "unknown_effect")

    consume_inventory_item_locked(locked_item, 1)
    return effect_summary
