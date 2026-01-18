"""
Item usage logic (warehouse-usable items + guest-target items).

This module depends on the core inventory operations in `core.py`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from django.db import transaction

from core.exceptions import GuestCapacityFullError, ItemNotConfiguredError, ItemNotUsableError
from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from gameplay.services.resources import grant_resources

from .core import add_item_to_inventory, consume_inventory_item_locked

# Do NOT `import random` here: tests monkeypatch `gameplay.services.inventory.random.random`.
from gameplay.services import inventory as inventory_pkg

# 不在仓库使用的物品提示信息
NON_WAREHOUSE_MESSAGES = {
    ItemTemplate.EffectType.SKILL_BOOK: "技能书请在门客详情页为指定门客使用",
    ItemTemplate.EffectType.EXPERIENCE_ITEM: "经验道具请在门客详情页为指定门客使用",
    ItemTemplate.EffectType.MEDICINE: "药品道具请在门客详情页为指定门客使用",
}


def _apply_resource_pack(item: InventoryItem) -> Dict[str, Any]:
    """使用资源包，发放资源奖励。"""
    payload = item.template.effect_payload or {}
    if not payload:
        raise ItemNotConfiguredError()
    result = grant_resources(item.manor, payload, item.template.name, ResourceEvent.Reason.ITEM_USE)
    parts = [f"{key}+{value}" for key, value in result.items()]
    result["_message"] = f"获得 {'、'.join(parts)}"
    return result


def _apply_peace_shield(item: InventoryItem) -> Dict[str, Any]:
    """使用免战牌，激活保护状态。"""
    from gameplay.services.raid import activate_peace_shield, get_active_raid_count, get_incoming_raids

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
    roll = inventory_pkg.random.random() * total_weight
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

    from guests.models import GuestTemplate
    from guests.services.recruitment import create_guest_from_template

    template = GuestTemplate.objects.filter(key=chosen_key).first()
    if not template:
        raise ValueError(f"门客模板不存在: {chosen_key}")

    guest = create_guest_from_template(
        manor=manor,
        template=template,
        rng=inventory_pkg.random.Random(),
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
        raise ValueError("请选择要重生的门客")
    key = item.template.key or ""
    if key.startswith("peace_shield_"):
        return _apply_peace_shield(item)
    raise ValueError("未知的道具效果")


def _apply_loot_box(item: InventoryItem) -> Dict[str, Any]:
    """使用宝箱类物品，按配置发放多种奖励。"""
    payload = item.template.effect_payload or {}
    if not payload:
        raise ItemNotConfiguredError()

    manor = item.manor
    rewards: List[str] = []

    # 1. 资源掉落（必定）
    resources = payload.get("resources") or {}
    if resources:
        result = grant_resources(manor, resources, item.template.name, ResourceEvent.Reason.ITEM_USE)
        parts = [f"{k}+{v}" for k, v in result.items()]
        rewards.append("资源：" + "、".join(parts))

    # 2. 装备掉落（可选）
    gear_keys = payload.get("gear_keys") or []
    for gear_key in gear_keys:
        from guests.models import GearTemplate
        from guests.services.equipment import give_gear

        gear_template = GearTemplate.objects.filter(key=gear_key).first()
        if gear_template:
            give_gear(manor, gear_template)
            rewards.append(f"装备【{gear_template.name}】")

    # 3. 技能书掉落（概率）
    skill_book_chance = payload.get("skill_book_chance", 0)
    skill_book_keys = payload.get("skill_book_keys", [])
    if skill_book_chance > 0 and skill_book_keys and inventory_pkg.random.random() < skill_book_chance:
        book_key = inventory_pkg.random.choice(skill_book_keys)
        try:
            add_item_to_inventory(manor, book_key, 1)
            book_template = ItemTemplate.objects.filter(key=book_key).first()
            book_name = book_template.name if book_template else book_key
            rewards.append(f"技能书【{book_name}】")
        except ValueError:
            pass

    reward_text = "、".join(rewards) if rewards else "空"
    return {
        "rewards": rewards,
        "_message": f"打开宝箱获得：{reward_text}",
    }


ITEM_EFFECT_HANDLERS = {
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
        ValueError: 物品不存在或不属于指定庄园
        InsufficientStockError: 物品数量不足
        ItemNotUsableError: 物品不可用
    """
    from core.exceptions import InsufficientStockError

    if not item.pk:
        raise ValueError("物品不存在")

    # 构建查询条件
    query_filter = {"pk": item.pk}
    if manor is not None:
        # 如果提供了manor，校验物品归属
        query_filter["manor"] = manor

    locked_item = (
        InventoryItem.objects.select_for_update()
        .select_related("template", "manor")
        .filter(**query_filter)
        .first()
    )
    if not locked_item:
        if manor is not None:
            raise ValueError("物品不存在或不属于您的庄园")
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


def _validate_guest_item_use(
    manor: Manor,
    item: InventoryItem,
    guest_id: int,
    action: str,
    deployed_message: str,
    working_message: str,
) -> tuple[InventoryItem, "Guest"]:
    """校验门客类道具的通用前置条件并加锁。"""
    from core.exceptions import InsufficientStockError
    from guests.models import Guest, GuestStatus

    if not item.pk:
        raise ValueError("物品不存在")
    locked_item = (
        InventoryItem.objects.select_for_update()
        .select_related("template", "manor")
        .filter(pk=item.pk, manor=manor)
        .first()
    )
    if not locked_item:
        raise ValueError("物品不存在或不属于您的庄园")

    payload = locked_item.template.effect_payload or {}
    if payload.get("action") != action:
        raise ValueError("物品类型错误")

    if locked_item.quantity <= 0:
        raise InsufficientStockError(locked_item.template.name, 1, locked_item.quantity)

    guest = (
        Guest.objects.select_for_update()
        .select_related("template")
        .filter(id=guest_id, manor=manor)
        .first()
    )
    if not guest:
        raise ValueError("门客不存在或不属于您的庄园")
    if guest.status == GuestStatus.DEPLOYED:
        raise ValueError(deployed_message)
    if guest.status == GuestStatus.WORKING:
        raise ValueError(working_message)

    return locked_item, guest


@transaction.atomic
def use_guest_rebirth_card(manor: Manor, item: InventoryItem, guest_id: int) -> Dict[str, Any]:
    """使用门客重生卡，将指定门客重置为1级。"""
    locked_item, guest = _validate_guest_item_use(
        manor,
        item,
        guest_id,
        "rebirth_guest",
        "门客正在出征中，无法重生",
        "门客正在打工中，无法重生",
    )

    old_level = guest.level
    guest_name = guest.display_name

    from guests.services import unequip_guest_item

    gear_items = list(guest.gear_items.select_related("template"))
    unequipped_count = 0
    for gear in gear_items:
        try:
            unequip_guest_item(gear, guest)
            unequipped_count += 1
        except Exception:
            pass

    skills_count = guest.guest_skills.count()
    guest.guest_skills.all().delete()

    template = guest.template

    from guests.utils.recruitment_variance import apply_recruitment_variance

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
        rng=inventory_pkg.random.Random(),
    )

    guest.level = 1
    guest.experience = 0
    guest.force = varied_attrs["force"]
    guest.intellect = varied_attrs["intellect"]
    guest.defense_stat = varied_attrs["defense"]
    guest.agility = varied_attrs["agility"]
    guest.luck = varied_attrs["luck"]
    guest.attribute_points = 0
    guest.attack_bonus = 0
    guest.defense_bonus = 0
    guest.hp_bonus = 0
    guest.training_target_level = 0
    guest.training_complete_at = None
    guest.status = GuestStatus.IDLE

    guest.initial_force = varied_attrs["force"]
    guest.initial_intellect = varied_attrs["intellect"]
    guest.initial_defense = varied_attrs["defense"]
    guest.initial_agility = varied_attrs["agility"]

    guest.allocated_force = 0
    guest.allocated_intellect = 0
    guest.allocated_defense = 0
    guest.allocated_agility = 0

    guest.xisuidan_used = 0

    guest.save(
        update_fields=[
            "level",
            "experience",
            "force",
            "intellect",
            "defense_stat",
            "agility",
            "luck",
            "attribute_points",
            "attack_bonus",
            "defense_bonus",
            "hp_bonus",
            "training_target_level",
            "training_complete_at",
            "status",
            "initial_force",
            "initial_intellect",
            "initial_defense",
            "initial_agility",
            "xisuidan_used",
            "allocated_force",
            "allocated_intellect",
            "allocated_defense",
            "allocated_agility",
        ]
    )

    guest.restore_full_hp()

    from guests.services.training import ensure_auto_training

    ensure_auto_training(guest)

    consume_inventory_item_locked(locked_item, 1)

    extras = []
    if unequipped_count > 0:
        extras.append(f"装备已归还仓库（{unequipped_count}件）")
    if skills_count > 0:
        extras.append(f"技能已清空（{skills_count}个）")
    extra_msg = "，" + "，".join(extras) if extras else ""

    return {
        "guest_name": guest_name,
        "old_level": old_level,
        "unequipped_count": unequipped_count,
        "skills_cleared": skills_count,
        "_message": f"门客 {guest_name} 已重生为1级（原{old_level}级）{extra_msg}",
    }


@transaction.atomic
def use_xisuidan(manor: Manor, item: InventoryItem, guest_id: int) -> Dict[str, Any]:
    """
    使用洗髓丹，重新随机门客的升级成长点数。
    """
    from guests.utils.attribute_growth import generate_growth_points
    locked_item, guest = _validate_guest_item_use(
        manor,
        item,
        guest_id,
        "reroll_growth",
        "门客正在出征中，无法洗髓",
        "门客正在打工中，无法洗髓",
    )

    guest_name = guest.display_name

    current_growth = guest.growth_points or {}
    current_total = sum(int(v or 0) for v in current_growth.values())

    rng = inventory_pkg.random.Random()
    new_growth = generate_growth_points(
        guest.template,
        levels=max(0, guest.level - 1),
        rng=rng,
    )
    new_total = sum(int(v or 0) for v in (new_growth or {}).values())

    growth_diff = new_total - current_total

    new_force = guest.initial_force + guest.allocated_force + new_growth["force"]
    new_intellect = guest.initial_intellect + guest.allocated_intellect + new_growth["intellect"]
    new_defense = guest.initial_defense + guest.allocated_defense + new_growth["defense"]
    new_agility = guest.initial_agility + guest.allocated_agility + new_growth["agility"]

    changes = {
        "force": new_force - guest.force,
        "intellect": new_intellect - guest.intellect,
        "defense": new_defense - guest.defense_stat,
        "agility": new_agility - guest.agility,
    }

    guest.growth_points = new_growth
    guest.force = new_force
    guest.intellect = new_intellect
    guest.defense_stat = new_defense
    guest.agility = new_agility
    guest.xisuidan_used += 1
    guest.save(update_fields=["growth_points", "force", "intellect", "defense_stat", "agility", "xisuidan_used"])

    consume_inventory_item_locked(locked_item, 1)

    attr_names = {"force": "武力", "intellect": "智力", "defense": "防御", "agility": "敏捷"}
    change_parts = []
    for attr, diff in changes.items():
        if diff != 0:
            sign = "+" if diff > 0 else ""
            change_parts.append(f"{attr_names[attr]}{sign}{diff}")

    if growth_diff > 0:
        msg = f"门客 {guest_name} 洗髓成功！成长点数+{growth_diff}（{current_total}→{new_total}）"
    else:
        msg = f"门客 {guest_name} 洗髓完成，成长点数未变（{current_total}点），属性重新分配"
    if change_parts:
        msg += f"，属性变化：{', '.join(change_parts)}"

    return {
        "guest_name": guest_name,
        "old_total": current_total,
        "new_total": new_total,
        "growth_diff": growth_diff,
        "changes": changes,
        "_message": msg,
    }


@transaction.atomic
def use_xidianka(manor: Manor, item: InventoryItem, guest_id: int) -> Dict[str, Any]:
    """
    使用洗点卡，重置门客的属性点分配。
    """
    locked_item, guest = _validate_guest_item_use(
        manor,
        item,
        guest_id,
        "reset_allocation",
        "门客正在出征中，无法使用洗点卡",
        "门客正在打工中，无法使用洗点卡",
    )

    guest_name = guest.display_name

    total_allocated = guest.allocated_force + guest.allocated_intellect + guest.allocated_defense + guest.allocated_agility
    if total_allocated == 0:
        raise ValueError("该门客没有分配过属性点，无需使用洗点卡")

    allocation_details = {
        "force": guest.allocated_force,
        "intellect": guest.allocated_intellect,
        "defense": guest.allocated_defense,
        "agility": guest.allocated_agility,
    }

    guest.force -= guest.allocated_force
    guest.intellect -= guest.allocated_intellect
    guest.defense_stat -= guest.allocated_defense
    guest.agility -= guest.allocated_agility

    guest.attribute_points += total_allocated

    guest.allocated_force = 0
    guest.allocated_intellect = 0
    guest.allocated_defense = 0
    guest.allocated_agility = 0

    guest.save(
        update_fields=[
            "force",
            "intellect",
            "defense_stat",
            "agility",
            "attribute_points",
            "allocated_force",
            "allocated_intellect",
            "allocated_defense",
            "allocated_agility",
        ]
    )

    consume_inventory_item_locked(locked_item, 1)

    attr_names = {"force": "武力", "intellect": "智力", "defense": "防御", "agility": "敏捷"}
    detail_parts = [f"{attr_names[k]}-{v}" for k, v in allocation_details.items() if v > 0]

    return {
        "guest_name": guest_name,
        "total_returned": total_allocated,
        "details": allocation_details,
        "_message": f"门客 {guest_name} 洗点成功！返还 {total_allocated} 属性点（{', '.join(detail_parts)}）",
    }
