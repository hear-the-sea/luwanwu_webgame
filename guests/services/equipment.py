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
    GuestNotIdleError,
    ItemNotFoundError,
)

if TYPE_CHECKING:
    from gameplay.models import Manor

from django.db import transaction

from ..models import GearItem, GearSlot, GearTemplate, Guest, GuestRarity, GuestStatus
from ..utils.equipment_utils import EQUIP_SLOT_MAP, SET_STAT_FIELD_MAP, compute_set_bonus

_GEAR_EXTRA_STAT_FIELDS = {
    "hp": "hp_bonus",
    "force": "force",
    "intellect": "intellect",
    "defense": "defense_stat",
    "agility": "agility",
    "luck": "luck",
}


def _slot_capacity(slot: str) -> int:
    return {
        GearSlot.DEVICE: 3,
        GearSlot.ORNAMENT: 3,
    }.get(slot, 1)


def _apply_template_stats_to_guest(guest: Guest, template, sign: int, updates: set[str]) -> None:
    guest.attack_bonus += sign * template.attack_bonus
    guest.defense_bonus += sign * template.defense_bonus
    for key, field in _GEAR_EXTRA_STAT_FIELDS.items():
        value = (template.extra_stats or {}).get(key)
        if value:
            setattr(guest, field, getattr(guest, field) + sign * int(value))
            updates.add(field)


def _clear_replaced_items(guest: Guest, existing_items: list[GearItem]) -> None:
    import logging

    from django.db.models import F

    from gameplay.models import InventoryItem, ItemTemplate

    logger = logging.getLogger(__name__)

    for item in existing_items:
        guest.attack_bonus -= item.template.attack_bonus
        guest.defense_bonus -= item.template.defense_bonus
        for key, field in _GEAR_EXTRA_STAT_FIELDS.items():
            value = (item.template.extra_stats or {}).get(key)
            if value:
                setattr(guest, field, getattr(guest, field) - int(value))
        item.guest = None
        item.save(update_fields=["guest"])

        # 修复：被替换的装备必须退回仓库
        # 1. 查找对应的 ItemTemplate (GearTemplate 与 ItemTemplate 通过 key 关联)
        item_template = ItemTemplate.objects.filter(key=item.template.key).first()
        if not item_template:
            logger.error(f"Cannot return gear to inventory: ItemTemplate not found for key {item.template.key}")
            continue

        # 2. 使用原子更新增加库存
        updated = InventoryItem.objects.filter(
            manor=guest.manor, template=item_template, storage_location=InventoryItem.StorageLocation.WAREHOUSE
        ).update(quantity=F("quantity") + 1)

        if updated == 0:
            # 3. 如果不存在则创建
            InventoryItem.objects.create(
                manor=guest.manor,
                template=item_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity=1,
            )


def _consume_warehouse_item_for_gear(guest: Guest, gear: GearItem) -> None:
    from django.db.models import F

    from gameplay.models import InventoryItem

    # 修复：使用 select_for_update 锁定库存行，防止并发双重消费
    inv_item = (
        InventoryItem.objects.select_for_update()
        .filter(
            manor=guest.manor,
            template__key=gear.template.key,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity__gt=0,  # 确保有库存
        )
        .order_by("id")
        .first()
    )

    if not inv_item:
        # 理论上 equip_guest 之前应该校验过，但并发下可能被抢占
        raise EquipmentError("装备库存不足")

    # 使用原子更新扣减库存
    InventoryItem.objects.filter(pk=inv_item.pk).update(quantity=F("quantity") - 1)

    # 清理零库存记录（再次检查以确保安全）
    InventoryItem.objects.filter(pk=inv_item.pk, quantity__lte=0).delete()


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
        manor=manor, template__effect_type__in=effect_types, storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).select_related("template")
    if not items:
        # No warehouse items for these slots — clean up any orphaned free GearItems
        target_slots = set(EQUIP_SLOT_MAP[et] for et in effect_types if et in EQUIP_SLOT_MAP)
        if target_slots:
            GearItem.objects.filter(manor=manor, guest__isnull=True, template__slot__in=target_slots).delete()
        return
    target_slots = set(EQUIP_SLOT_MAP[et] for et in effect_types if et in EQUIP_SLOT_MAP)
    synced_slots: set[str] = set()
    for inv in items:
        slot = EQUIP_SLOT_MAP.get(inv.template.effect_type)
        if not slot:
            continue
        synced_slots.add(slot)
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

    # Clean up free GearItems for slots that had no warehouse items
    orphan_slots = target_slots - synced_slots
    if orphan_slots:
        GearItem.objects.filter(manor=manor, guest__isnull=True, template__slot__in=orphan_slots).delete()


@transaction.atomic
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
    # 使用 select_for_update 锁定装备和门客，防止并发问题
    gear = GearItem.objects.select_for_update().get(pk=gear.pk)
    guest = Guest.objects.select_for_update().get(pk=guest.pk)
    if guest.status != GuestStatus.IDLE:
        raise GuestNotIdleError(guest)

    slot = gear.template.slot
    capacity = _slot_capacity(slot)
    if gear.manor_id != guest.manor_id:
        raise EquipmentError("无法装备其他庄园的装备")
    if gear.guest_id and gear.guest_id != guest.id:
        raise EquipmentAlreadyEquippedError()
    if gear.guest_id == guest.id:
        return gear
    # 锁定该槽位的现有装备，防止并发修改
    existing_items = list(guest.gear_items.select_for_update().filter(template__slot=slot))
    for item in existing_items:
        if item.template.name == gear.template.name:
            raise DuplicateEquipmentError()
    if capacity == 1 and existing_items:
        _clear_replaced_items(guest, existing_items)
    elif capacity > 1 and len(existing_items) >= capacity:
        raise EquipmentSlotFullError(slot)

    gear.guest = guest
    gear.save(update_fields=["guest"])

    _consume_warehouse_item_for_gear(guest, gear)

    updates = {"attack_bonus", "defense_bonus"}
    _apply_template_stats_to_guest(guest, gear.template, +1, updates)
    guest.save(update_fields=list(updates))
    apply_set_bonuses(guest)

    # 替换装备后，如果当前生命值超过最大生命值，则调整为最大生命值
    if guest.current_hp > guest.max_hp:
        guest.current_hp = guest.max_hp
        guest.save(update_fields=["current_hp"])

    return gear


@transaction.atomic
def unequip_guest_item(gear: GearItem, guest: Guest, *, allow_injured: bool = False) -> GearItem:
    """
    卸下门客的装备道具。
    """
    from gameplay.models import InventoryItem

    # 并发安全：锁定装备和门客，防止并发卸载/穿戴
    gear = GearItem.objects.select_for_update().get(pk=gear.pk)
    guest = Guest.objects.select_for_update().get(pk=guest.pk)
    allowed_statuses = {GuestStatus.IDLE}
    if allow_injured:
        allowed_statuses.add(GuestStatus.INJURED)
    if guest.status not in allowed_statuses:
        raise GuestNotIdleError(guest)

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
    from django.db.models import F

    # 使用原子更新增加库存，防止并发覆盖
    # 先尝试更新现有记录
    updated = InventoryItem.objects.filter(
        manor=guest.manor, template=item_template, storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).update(quantity=F("quantity") + 1)

    if updated == 0:
        # 如果不存在，则创建（加锁防止并发创建冲突）
        # 注意：这里理论上仍有极其微小的竞态（两个并发请求同时发现 updated==0），
        # 但 InventoryItem通常有唯一约束(manor, template, location)。
        # 若发生 IntegrityError，让应用层重试或由上层事务回滚即可。
        InventoryItem.objects.create(
            manor=guest.manor,
            template=item_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity=1,
        )

    return gear
