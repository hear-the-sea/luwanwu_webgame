"""
背包物品管理服务
"""

from __future__ import annotations

import random
from typing import Any, Callable, Dict, List

from django.db import transaction
from django.db.models import F

from core.exceptions import (
    GuestCapacityFullError,
    InsufficientStockError,
    ItemNotConfiguredError,
    ItemNotUsableError,
)
from ..models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from .resources import grant_resources

# 粮食物品模板 key
GRAIN_ITEM_KEY = "grain"


def sync_manor_grain(manor: Manor) -> None:
    """
    同步庄园粮食数量，使 Manor.grain 等于仓库中粮食物品的数量。

    藏宝阁中的粮食不计入庄园粮食储量。

    Args:
        manor: 庄园对象
    """
    grain_item = InventoryItem.objects.filter(
        manor=manor,
        template__key=GRAIN_ITEM_KEY,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).first()

    grain_quantity = grain_item.quantity if grain_item else 0

    if manor.grain != grain_quantity:
        Manor.objects.filter(pk=manor.pk).update(grain=grain_quantity)
        manor.grain = grain_quantity


def list_inventory_items(manor: Manor):
    """
    获取庄园的背包物品列表。

    Args:
        manor: 庄园对象

    Returns:
        物品查询集
    """
    return manor.inventory_items.select_related("template").order_by("template__name")


def get_item_quantity(manor: Manor, item_key: str) -> int:
    """
    获取庄园仓库中指定物品的数量。

    只统计仓库中的物品，藏宝阁中的物品不计入。

    Args:
        manor: 庄园对象
        item_key: 物品模板key

    Returns:
        物品数量，如果物品不存在则返回0
    """
    item = InventoryItem.objects.filter(
        manor=manor,
        template__key=item_key,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).first()
    return item.quantity if item else 0


def add_item_to_inventory(
    manor: Manor,
    item_key: str,
    quantity: int = 1,
    storage_location: str = InventoryItem.StorageLocation.WAREHOUSE,
) -> InventoryItem:
    """
    向庄园背包添加物品。

    Args:
        manor: 庄园对象
        item_key: 物品模板key
        quantity: 数量
        storage_location: 存储位置（仓库或藏宝阁）

    Returns:
        InventoryItem: 背包物品对象

    Raises:
        ValueError: 物品模板不存在时抛出
    """
    template = ItemTemplate.objects.filter(key=item_key).first()
    if not template:
        raise ValueError(f"物品模板不存在: {item_key}")

    with transaction.atomic():
        item, created = InventoryItem.objects.get_or_create(
            manor=manor,
            template=template,
            storage_location=storage_location,
            defaults={"quantity": 0},
        )
        item.quantity += quantity
        item.save(update_fields=["quantity"])

        # 粮食存入仓库时，同步更新 Manor.grain
        if item_key == GRAIN_ITEM_KEY and storage_location == InventoryItem.StorageLocation.WAREHOUSE:
            Manor.objects.filter(pk=manor.pk).update(grain=F("grain") + quantity)
            manor.grain = getattr(manor, "grain", 0) + quantity

    return item


# 物品效果处理器类型
ItemEffectHandler = Callable[[InventoryItem], Dict[str, Any]]

# 不在仓库使用的物品提示信息
NON_WAREHOUSE_MESSAGES = {
    ItemTemplate.EffectType.SKILL_BOOK: "技能书请在门客详情页为指定门客使用",
    ItemTemplate.EffectType.EXPERIENCE_ITEM: "经验道具请在门客详情页为指定门客使用",
    ItemTemplate.EffectType.MEDICINE: "药品道具请在门客详情页为指定门客使用",
}


def _apply_resource_pack(item: InventoryItem) -> Dict[str, Any]:
    """
    使用资源包，发放资源奖励。

    Args:
        item: 背包物品对象

    Returns:
        奖励资源字典

    Raises:
        ItemNotConfiguredError: 物品未配置奖励时抛出
    """
    payload = item.template.effect_payload or {}
    if not payload:
        raise ItemNotConfiguredError()
    result = grant_resources(item.manor, payload, item.template.name, ResourceEvent.Reason.ITEM_USE)
    # 生成人类友好的提示
    parts = [f"{key}+{value}" for key, value in result.items()]
    result["_message"] = f"获得 {'、'.join(parts)}"
    return result


def _apply_peace_shield(item: InventoryItem) -> Dict[str, Any]:
    """
    使用免战牌，激活保护状态。

    Args:
        item: 背包物品对象

    Returns:
        效果摘要字典（包含保护时长）

    Raises:
        ItemNotConfiguredError: 物品未配置时长时抛出
        ValueError: 无法使用免战牌时抛出
    """
    from .raid import activate_peace_shield, get_active_raid_count, get_incoming_raids

    payload = item.template.effect_payload or {}
    duration = payload.get("duration")
    if not duration:
        raise ItemNotConfiguredError()

    manor = item.manor

    # 检查是否有出征中的队伍
    active_raids = get_active_raid_count(manor)
    if active_raids > 0:
        raise ValueError("有出征中的队伍，无法使用免战牌")

    # 检查是否有敌军来袭
    incoming = get_incoming_raids(manor)
    if incoming:
        raise ValueError("有敌军来袭，无法使用免战牌")

    # 激活免战牌保护
    activate_peace_shield(manor, duration)

    # 格式化时长显示
    hours = duration // 3600
    return {
        "duration_seconds": duration,
        "duration_hours": hours,
        "_message": f"获得 {hours}小时 免战保护",
    }


def _apply_tool(item: InventoryItem) -> Dict[str, Any]:
    """
    使用道具类物品（统一 effect_type=tool）。

    目前仓库可使用的道具包含免战牌系列、门客召唤卡；其他道具应在对应功能页面使用。
    """
    payload = item.template.effect_payload or {}
    if payload.get("action") == "summon_guest":
        return _apply_guest_summon(item)
    key = item.template.key or ""
    if key.startswith("peace_shield_"):
        return _apply_peace_shield(item)
    raise ValueError("未知的道具效果")


def _apply_guest_summon(item: InventoryItem) -> Dict[str, Any]:
    """
    使用门客召唤卡：按权重随机获得一个门客模板并直接加入聚贤庄。

    effect_payload 示例：
      action: summon_guest
      choices:
        - template_key: pubayi_blue
          weight: 10
        - template_key: pubayi_green
          weight: 90
    """
    payload = item.template.effect_payload or {}
    choices = payload.get("choices") or []
    if not isinstance(choices, list):
        raise ItemNotConfiguredError()

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

    if not template_keys:
        raise ItemNotConfiguredError()

    total_weight = sum(weights)
    roll = random.random() * total_weight
    chosen_key = template_keys[-1]
    cumulative = 0
    for template_key, weight in zip(template_keys, weights):
        cumulative += weight
        if roll < cumulative:
            chosen_key = template_key
            break

    manor = item.manor
    capacity = manor.guest_capacity
    current = manor.guests.count()
    if current >= capacity:
        raise GuestCapacityFullError()

    from guests.models import Guest, GuestTemplate
    from guests.utils.recruitment_variance import apply_recruitment_variance

    template = GuestTemplate.objects.filter(key=chosen_key).first()
    if not template:
        raise ValueError(f"门客模板不存在: {chosen_key}")

    rng = random.Random()
    gender_choice = template.default_gender
    if not gender_choice or gender_choice == "unknown":
        gender_choice = rng.choice(["male", "female"])
    morality_value = template.default_morality or rng.randint(30, 100)

    template_attrs = {
        "force": template.base_attack,
        "intellect": template.base_intellect,
        "defense": template.base_defense,
        "agility": template.base_agility,
        "luck": template.base_luck,
    }
    varied_attrs = apply_recruitment_variance(
        template_attrs,
        rarity=template.rarity,
        archetype=template.archetype,
        rng=rng,
    )

    guest = Guest.objects.create(
        manor=manor,
        template=template,
        custom_name="",
        force=varied_attrs["force"],
        intellect=varied_attrs["intellect"],
        defense_stat=varied_attrs["defense"],
        agility=varied_attrs["agility"],
        luck=varied_attrs["luck"],
        loyalty=60,
        gender=gender_choice,
        morality=morality_value,
    )
    guest.current_hp = guest.max_hp
    guest.save(update_fields=["current_hp"])

    from guests.services.recruitment import grant_template_skills

    grant_template_skills(guest)

    rarity_display = template.get_rarity_display()
    return {
        "获得门客": guest.display_name,
        "稀有度": rarity_display,
        "_message": f"获得门客 {guest.display_name}（{rarity_display}）",
    }


# 物品效果处理器映射
ITEM_EFFECT_HANDLERS: Dict[str, ItemEffectHandler] = {
    ItemTemplate.EffectType.RESOURCE_PACK: _apply_resource_pack,
    ItemTemplate.EffectType.TOOL: _apply_tool,
}


def consume_inventory_item(item_or_manor, item_key_or_amount=1, amount: int = 1) -> None:
    """
    消耗背包物品。

    支持两种调用方式：
    1. consume_inventory_item(item, amount) - 直接传入物品对象
    2. consume_inventory_item(manor, item_key, amount) - 传入庄园和物品key

    Args:
        item_or_manor: 背包物品对象或庄园对象
        item_key_or_amount: 物品key（字符串）或消耗数量（整数）
        amount: 消耗数量（仅在第一种调用方式时使用）

    Raises:
        InsufficientStockError: 物品库存不足时抛出
        ValueError: 物品不存在时抛出
    """
    # 判断调用方式
    if isinstance(item_or_manor, InventoryItem):
        # 方式1: consume_inventory_item(item, amount)
        item = item_or_manor
        consume_amount = item_key_or_amount if isinstance(item_key_or_amount, int) else 1
    elif isinstance(item_or_manor, Manor):
        # 方式2: consume_inventory_item(manor, item_key, amount)
        manor = item_or_manor
        item_key = item_key_or_amount
        consume_amount = amount

        item = InventoryItem.objects.filter(
            manor=manor,
            template__key=item_key,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE
        ).select_related("template").first()

        if not item:
            raise ValueError(f"物品不存在: {item_key}")
    else:
        raise TypeError("第一个参数必须是 InventoryItem 或 Manor 对象")

    if consume_amount <= 0:
        return
    if item.quantity < consume_amount:
        raise InsufficientStockError(item.template.name, consume_amount, item.quantity)

    item.quantity -= consume_amount

    # 粮食从仓库消耗时，同步更新 Manor.grain
    if (item.template.key == GRAIN_ITEM_KEY
            and item.storage_location == InventoryItem.StorageLocation.WAREHOUSE):
        manor_obj = item.manor
        Manor.objects.filter(pk=manor_obj.pk).update(grain=F("grain") - consume_amount)

    if item.quantity <= 0:
        item.delete()
    else:
        item.save(update_fields=["quantity"])


@transaction.atomic
def use_inventory_item(item: InventoryItem) -> Dict[str, Any]:
    """
    使用背包物品。

    Args:
        item: 背包物品对象

    Returns:
        物品效果摘要字典

    Raises:
        InsufficientStockError: 物品库存不足时抛出
        ItemNotUsableError: 物品无法使用时抛出
    """
    if item.quantity <= 0:
        raise InsufficientStockError(item.template.name, 1, item.quantity)

    template = item.template

    # 检查物品是否可在仓库使用
    if not template.is_usable:
        raise ItemNotUsableError(template.name, "not_warehouse_usable")

    handler = ITEM_EFFECT_HANDLERS.get(template.effect_type)
    if handler:
        effect_summary = handler(item)
    else:
        effect_type = template.effect_type or ""
        if effect_type.startswith("equip_"):
            raise ItemNotUsableError(template.name, "equip_in_guest_detail")
        message = NON_WAREHOUSE_MESSAGES.get(effect_type)
        if message:
            raise ItemNotUsableError(template.name, effect_type)
        raise ItemNotUsableError(template.name, "unknown_effect")

    consume_inventory_item(item)
    return effect_summary
