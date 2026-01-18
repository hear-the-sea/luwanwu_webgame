"""
门客装备管理服务
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from core.exceptions import (
    DuplicateEquipmentError,
    EquipmentAlreadyEquippedError,
    EquipmentError,
    EquipmentNotEquippedError,
    EquipmentSlotFullError,
    ItemNotFoundError,
)

if TYPE_CHECKING:
    from gameplay.models import Manor

from ..models import GearItem, GearSlot, GearTemplate, Guest, GuestRarity
from ..utils.equipment_utils import EQUIP_SLOT_MAP, SET_STAT_FIELD_MAP, compute_set_bonus


def apply_set_bonuses(guest: Guest) -> Dict[str, int]:
    """
    重新计算套装效果，并将其数值写回门客属性。上一轮套装效果会被先撤销。
    """
    previous = guest.gear_set_bonus or {}
    current = compute_set_bonus(guest.gear_items.select_related("template"))
    if previous == current:
        return current

    updates = set()
    # 移除旧的套装效果
    for stat, field in SET_STAT_FIELD_MAP.items():
        prev_value = int(previous.get(stat, 0) or 0)
        if prev_value:
            setattr(guest, field, getattr(guest, field) - prev_value)
            updates.add(field)

    # 应用当前套装效果
    for stat, value in current.items():
        field = SET_STAT_FIELD_MAP.get(stat)
        if not field:
            continue
        val = int(value or 0)
        if val:
            setattr(guest, field, getattr(guest, field) + val)
            updates.add(field)

    guest.gear_set_bonus = current
    updates.add("gear_set_bonus")
    if updates:
        guest.save(update_fields=list(updates))
    return current


def give_gear(manor: Manor, template: GearTemplate) -> GearItem:
    """创建一个装备道具"""
    return GearItem.objects.create(manor=manor, template=template)


def ensure_inventory_gears(manor: Manor, *, slot: str | None = None) -> None:
    """
    同步庄园背包中的装备道具到门客装备系统。
    确保背包数量与装备模板数量匹配。

    IMPORTANT: Only count items in WAREHOUSE since equip_guest consumes from WAREHOUSE.
    """
    from gameplay.models import InventoryItem

    effect_types = list(EQUIP_SLOT_MAP.keys())
    if slot:
        effect_types = [key for key, mapped_slot in EQUIP_SLOT_MAP.items() if mapped_slot == slot]
        if not effect_types:
            return
    items = InventoryItem.objects.filter(
        manor=manor,
        template__effect_type__in=effect_types,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).select_related("template")
    if not items:
        return
    for inv in items:
        slot = EQUIP_SLOT_MAP.get(inv.template.effect_type)
        if not slot:
            continue
        payload = inv.template.effect_payload or {}
        extra_stats = {k: int(v) for k, v in payload.items() if isinstance(v, (int, float))}
        defaults = {
            "name": inv.template.name,
            "slot": slot,
            "rarity": getattr(inv.template, "rarity", GuestRarity.GRAY),
            "set_key": payload.get("set_key", ""),
            "set_description": payload.get("set_description", ""),
            "set_bonus": payload.get("set_bonus", {}),
            "attack_bonus": 0,
            "defense_bonus": 0,
            "extra_stats": extra_stats,
        }
        gear_template, _ = GearTemplate.objects.update_or_create(key=inv.template.key, defaults=defaults)
        free_qs = manor.gears.filter(template=gear_template, guest__isnull=True)
        free_count = free_qs.count()
        target_free = max(0, inv.quantity)
        if free_count < target_free:
            missing = target_free - free_count
            GearItem.objects.bulk_create([GearItem(manor=manor, template=gear_template) for _ in range(missing)])
        elif free_count > target_free:
            to_delete = free_qs[: free_count - target_free]
            GearItem.objects.filter(id__in=[g.id for g in to_delete]).delete()


def equip_guest(gear: GearItem, guest: Guest) -> GearItem:
    """
    为门客装备道具。

    Args:
        gear: 要装备的道具
        guest: 门客对象

    Returns:
        装备后的道具对象

    Raises:
        EquipmentError: 装备失败时抛出异常
    """
    from gameplay.models import InventoryItem

    slot_capacity = {
        GearSlot.DEVICE: 3,
        GearSlot.ORNAMENT: 3,
    }
    slot = gear.template.slot
    capacity = slot_capacity.get(slot, 1)
    if gear.manor != guest.manor:
        raise EquipmentError("无法装备其他庄园的装备")
    if gear.guest and gear.guest != guest:
        raise EquipmentAlreadyEquippedError()
    if gear.guest_id == guest.id:
        return gear
    existing_items = list(guest.gear_items.filter(template__slot=slot))
    for item in existing_items:
        if item.template.name == gear.template.name:
            raise DuplicateEquipmentError()
    if capacity == 1 and existing_items:
        # 替换装备时，完整移除旧装备的所有属性加成
        for item in existing_items:
            guest.attack_bonus -= item.template.attack_bonus
            guest.defense_bonus -= item.template.defense_bonus
            # 移除旧装备的 extra_stats 属性
            old_extra_stats = item.template.extra_stats or {}
            for key, field in {
                "hp": "hp_bonus",
                "force": "force",
                "intellect": "intellect",
                "defense": "defense_stat",
                "agility": "agility",
                "luck": "luck",
            }.items():
                value = old_extra_stats.get(key)
                if value:
                    setattr(guest, field, getattr(guest, field) - int(value))
            item.guest = None
            item.save(update_fields=["guest"])
    elif capacity > 1 and len(existing_items) >= capacity:
        raise EquipmentSlotFullError(slot)
    gear.guest = guest
    gear.save(update_fields=["guest"])
    # 从背包中消耗一个道具
    # IMPORTANT: Must specify storage_location to avoid ambiguity
    # when the same template exists in both warehouse and treasury
    inv_item = InventoryItem.objects.filter(
        manor=guest.manor,
        template__key=gear.template.key,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).order_by("id").first()
    if inv_item and inv_item.quantity > 0:
        inv_item.quantity -= 1
        if inv_item.quantity <= 0:
            inv_item.delete()
        else:
            inv_item.save(update_fields=["quantity"])
    extra_stats = gear.template.extra_stats or {}
    updates = {"attack_bonus", "defense_bonus"}
    guest.attack_bonus += gear.template.attack_bonus
    guest.defense_bonus += gear.template.defense_bonus
    for key, field in {
        "hp": "hp_bonus",
        "force": "force",
        "intellect": "intellect",
        "defense": "defense_stat",
        "agility": "agility",
        "luck": "luck",
    }.items():
        value = extra_stats.get(key)
        if value:
            setattr(guest, field, getattr(guest, field) + int(value))
            updates.add(field)
    guest.save(update_fields=list(updates))
    apply_set_bonuses(guest)

    # 替换装备后，如果当前生命值超过最大生命值，则调整为最大生命值
    if guest.current_hp > guest.max_hp:
        guest.current_hp = guest.max_hp
        guest.save(update_fields=["current_hp"])

    return gear


def unequip_guest_item(gear: GearItem, guest: Guest) -> GearItem:
    """
    卸下门客的装备道具。

    Args:
        gear: 要卸下的道具
        guest: 门客对象

    Returns:
        卸下后的道具对象

    Raises:
        EquipmentError: 卸下失败时抛出异常
    """
    from gameplay.models import InventoryItem

    if gear.manor != guest.manor:
        raise EquipmentError("无法卸下其他庄园的装备")
    if gear.guest_id != guest.id:
        raise EquipmentNotEquippedError()
    from gameplay.models import ItemTemplate

    item_template = ItemTemplate.objects.filter(key=gear.template.key).first()
    if not item_template:
        raise ItemNotFoundError("找不到对应的装备模板，无法入库")
    extra_stats = gear.template.extra_stats or {}
    updates = {"attack_bonus", "defense_bonus"}
    guest.attack_bonus -= gear.template.attack_bonus
    guest.defense_bonus -= gear.template.defense_bonus
    for key, field in {
        "hp": "hp_bonus",
        "force": "force",
        "intellect": "intellect",
        "defense": "defense_stat",
        "agility": "agility",
        "luck": "luck",
    }.items():
        value = extra_stats.get(key)
        if value:
            setattr(guest, field, getattr(guest, field) - int(value))
            updates.add(field)
    gear.guest = None
    gear.save(update_fields=["guest"])
    guest.save(update_fields=list(updates))
    apply_set_bonuses(guest)

    # 装备拆下后，如果当前生命值超过最大生命值，则调整为最大生命值
    if guest.current_hp > guest.max_hp:
        guest.current_hp = guest.max_hp
        guest.save(update_fields=["current_hp"])

    # 装备退回到背包
    # IMPORTANT: Must specify storage_location to avoid MultipleObjectsReturned
    # when the same template exists in both warehouse and treasury
    inv_item, _ = InventoryItem.objects.get_or_create(
        manor=guest.manor,
        template=item_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": 0}
    )
    inv_item.quantity += 1
    inv_item.save(update_fields=["quantity"])
    return gear
