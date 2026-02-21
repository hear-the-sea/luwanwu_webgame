"""
Guest-target item usage helpers (rebirth / growth reroll / allocation reset).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from django.db import transaction

from gameplay.models import InventoryItem, Manor

# Keep compatibility with tests monkeypatching `gameplay.services.inventory.random`.
from gameplay.services import inventory as inventory_pkg
from guests.models import Guest, GuestStatus

from .core import consume_inventory_item_locked

logger = logging.getLogger(__name__)

XISUIDAN_MAX_REROLL_ATTEMPTS = 32


def _validate_guest_item_use(
    manor: Manor,
    item: InventoryItem,
    guest_id: int,
    action: str,
    deployed_message: str,
    working_message: str,
) -> tuple[InventoryItem, Guest]:
    """Validate guest-target item usage prerequisites and lock related rows."""
    from core.exceptions import InsufficientStockError

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

    guest = Guest.objects.select_for_update().select_related("template").filter(id=guest_id, manor=manor).first()
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
    # 死锁预防：统一锁顺序 Manor -> InventoryItem -> Guest
    Manor.objects.select_for_update().get(pk=manor.pk)

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
        except (ValueError, TypeError) as exc:
            logger.warning("门客重生时装备卸载失败: guest_id=%s, gear_id=%s, error=%s", guest.pk, gear.pk, exc)
        except Exception as exc:
            logger.exception(
                "门客重生时装备卸载异常: guest_id=%s gear_id=%s error=%s",
                guest.pk,
                gear.pk,
                exc,
            )

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
    """使用洗髓丹，重新随机门客的升级成长点数。"""
    # 死锁预防：统一锁顺序 Manor -> InventoryItem -> Guest
    Manor.objects.select_for_update().get(pk=manor.pk)

    from guests.utils.attribute_growth import allocate_level_up_attributes

    locked_item, guest = _validate_guest_item_use(
        manor,
        item,
        guest_id,
        "reroll_growth",
        "门客正在出征中，无法洗髓",
        "门客正在打工中，无法洗髓",
    )

    guest_name = guest.display_name

    current_growth = {
        "force": max(0, guest.force - guest.initial_force - guest.allocated_force),
        "intellect": max(0, guest.intellect - guest.initial_intellect - guest.allocated_intellect),
        "defense": max(0, guest.defense_stat - guest.initial_defense - guest.allocated_defense),
        "agility": max(0, guest.agility - guest.initial_agility - guest.allocated_agility),
    }
    current_total = sum(int(v or 0) for v in current_growth.values())

    levels = max(0, guest.level - 1)
    rng = inventory_pkg.random.Random()

    best_growth = allocate_level_up_attributes(guest, levels=levels, rng=rng)
    best_total = sum(int(v or 0) for v in (best_growth or {}).values())

    attempts_remaining = XISUIDAN_MAX_REROLL_ATTEMPTS - 1
    while best_total < current_total and attempts_remaining > 0:
        candidate_growth = allocate_level_up_attributes(guest, levels=levels, rng=rng)
        candidate_total = sum(int(v or 0) for v in (candidate_growth or {}).values())
        if candidate_total > best_total:
            best_growth = candidate_growth
            best_total = candidate_total
        attempts_remaining -= 1

    if best_total < current_total:
        new_growth = current_growth
        new_total = current_total
    else:
        new_growth = best_growth
        new_total = best_total

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

    guest.force = new_force
    guest.intellect = new_intellect
    guest.defense_stat = new_defense
    guest.agility = new_agility
    guest.xisuidan_used += 1
    guest.save(update_fields=["force", "intellect", "defense_stat", "agility", "xisuidan_used"])

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
    """使用洗点卡，重置门客的属性点分配。"""
    # 死锁预防：统一锁顺序 Manor -> InventoryItem -> Guest
    Manor.objects.select_for_update().get(pk=manor.pk)

    locked_item, guest = _validate_guest_item_use(
        manor,
        item,
        guest_id,
        "reset_allocation",
        "门客正在出征中，无法使用洗点卡",
        "门客正在打工中，无法使用洗点卡",
    )

    guest_name = guest.display_name

    total_allocated = (
        guest.allocated_force + guest.allocated_intellect + guest.allocated_defense + guest.allocated_agility
    )
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
