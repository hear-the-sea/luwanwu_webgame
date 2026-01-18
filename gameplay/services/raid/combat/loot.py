"""Raid loot calculation/apply helpers (split from legacy combat.py)."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from django.db import IntegrityError
from django.db.models import F

from gameplay.services.raid import combat as combat_pkg

from ....models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from ...resources import log_resource_gain


def _calculate_loot(defender: Manor) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    计算战利品。

    Returns:
        (掠夺的资源, 掠夺的物品)
    """
    # 资源掠夺：10%~30%
    loot_percent = combat_pkg.random.uniform(
        combat_pkg.PVPConstants.LOOT_RESOURCE_MIN_PERCENT,
        combat_pkg.PVPConstants.LOOT_RESOURCE_MAX_PERCENT,
    )

    loot_resources: Dict[str, int] = {}
    if defender.grain > 0:
        loot_grain = min(int(defender.grain * loot_percent), 10000)  # 单次上限
        if loot_grain > 0:
            loot_resources["grain"] = loot_grain

    if defender.silver > 0:
        loot_silver = min(int(defender.silver * loot_percent), 10000)
        if loot_silver > 0:
            loot_resources["silver"] = loot_silver

    # 物品掠夺
    loot_items: Dict[str, int] = {}
    base_qs = InventoryItem.objects.filter(
        manor=defender,
        template__tradeable=True,
        quantity__gt=0,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    items_looted = 0
    max_loot_items = combat_pkg.PVPConstants.LOOT_ITEM_MAX_COUNT

    # 小库存：一次性拉取并打乱顺序（避免按DB默认顺序带来的偏差）
    total_candidates = base_qs.count()
    if total_candidates <= combat_pkg.LOOT_ITEM_SMALL_INVENTORY_THRESHOLD:
        rows = list(base_qs.values("quantity", "template__key", "template__rarity"))
        combat_pkg.random.shuffle(rows)
    else:
        # 大库存：分批抽样，限制单次扫描上限，避免极端情况下全表遍历
        seen_ids: set[int] = set()
        for _ in range(combat_pkg.LOOT_ITEM_SAMPLE_MAX_BATCHES):
            if items_looted >= max_loot_items:
                break

            remaining_qs = base_qs.exclude(id__in=seen_ids) if seen_ids else base_qs
            remaining_count = remaining_qs.count()
            if remaining_count <= 0:
                break

            batch_size = min(combat_pkg.LOOT_ITEM_SAMPLE_BATCH_SIZE, remaining_count)
            max_offset = max(0, remaining_count - batch_size)
            offset = combat_pkg.random.randint(0, max_offset) if max_offset else 0

            batch_rows = list(
                remaining_qs.order_by("id").values("id", "quantity", "template__key", "template__rarity")[offset : offset + batch_size]
            )
            if not batch_rows:
                continue

            for row in batch_rows:
                seen_ids.add(int(row["id"]))

            combat_pkg.random.shuffle(batch_rows)
            for row in batch_rows:
                if items_looted >= max_loot_items:
                    break

                quantity = int(row.get("quantity", 0) or 0)
                if quantity <= 0:
                    continue

                template_key = row.get("template__key")
                if not template_key:
                    continue
                template_key = str(template_key)
                if template_key in loot_items:
                    continue

                # 计算掠夺概率
                rarity = (row.get("template__rarity") or "gray")
                if not isinstance(rarity, str):
                    rarity = str(rarity)
                rarity_mult = combat_pkg.PVPConstants.RARITY_LOOT_MULTIPLIER.get(rarity, 1.0)
                loot_chance = combat_pkg.PVPConstants.LOOT_ITEM_BASE_CHANCE * rarity_mult

                if combat_pkg.random.random() < loot_chance:
                    # 掠夺数量
                    max_qty = min(
                        int(quantity * combat_pkg.PVPConstants.LOOT_ITEM_MAX_QUANTITY_PERCENT),
                        combat_pkg.PVPConstants.LOOT_ITEM_MAX_QUANTITY,
                    )
                    loot_qty = combat_pkg.random.randint(1, max(1, max_qty))
                    loot_qty = min(loot_qty, quantity)

                    if loot_qty > 0:
                        loot_items[template_key] = loot_qty
                        items_looted += 1

        return loot_resources, loot_items

    # 小库存路径：直接遍历打乱后的候选
    for row in rows:
        if items_looted >= max_loot_items:
            break

        quantity = int(row.get("quantity", 0) or 0)
        if quantity <= 0:
            continue

        template_key = row.get("template__key")
        if not template_key:
            continue
        template_key = str(template_key)
        if template_key in loot_items:
            continue

        rarity = (row.get("template__rarity") or "gray")
        if not isinstance(rarity, str):
            rarity = str(rarity)
        rarity_mult = combat_pkg.PVPConstants.RARITY_LOOT_MULTIPLIER.get(rarity, 1.0)
        loot_chance = combat_pkg.PVPConstants.LOOT_ITEM_BASE_CHANCE * rarity_mult

        if combat_pkg.random.random() < loot_chance:
            max_qty = min(
                int(quantity * combat_pkg.PVPConstants.LOOT_ITEM_MAX_QUANTITY_PERCENT),
                combat_pkg.PVPConstants.LOOT_ITEM_MAX_QUANTITY,
            )
            loot_qty = combat_pkg.random.randint(1, max(1, max_qty))
            loot_qty = min(loot_qty, quantity)
            if loot_qty > 0:
                loot_items[template_key] = loot_qty
                items_looted += 1

    return loot_resources, loot_items


def _apply_loot(
    defender: Manor, loot_resources: Dict[str, int], loot_items: Dict[str, int], locked_manor: Manor | None = None
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    从防守方扣除被掠夺的资源和物品，返回实际扣除量。
    """
    manor = locked_manor or Manor.objects.select_for_update().get(pk=defender.pk)
    actual_resources: Dict[str, int] = {}
    actual_items: Dict[str, int] = {}

    # 扣除资源（按当前可用量裁剪，避免不足导致回滚）
    for resource_key, amount in loot_resources.items():
        if amount <= 0:
            continue
        current_value = getattr(manor, resource_key, 0)
        deducted = min(current_value, amount)
        if deducted <= 0:
            continue
        setattr(manor, resource_key, current_value - deducted)
        actual_resources[resource_key] = deducted

    if actual_resources:
        manor.save(update_fields=list(actual_resources.keys()))
        log_resource_gain(
            manor,
            {key: -val for key, val in actual_resources.items()},
            ResourceEvent.Reason.ADMIN_ADJUST,
            note="踢馆被掠夺",
        )

    # 扣除物品（按当前库存裁剪）
    for item_key, qty in loot_items.items():
        if qty <= 0:
            continue
        try:
            item = InventoryItem.objects.select_for_update().get(
                manor=defender,
                template__key=item_key,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
        except InventoryItem.DoesNotExist:
            continue
        deducted = min(item.quantity, qty)
        if deducted <= 0:
            continue
        item.quantity -= deducted
        if item.quantity <= 0:
            item.delete()
        else:
            item.save(update_fields=["quantity", "updated_at"])
        actual_items[item_key] = deducted

    return actual_resources, actual_items


def _format_loot_description(resources: Dict[str, int], items: Dict[str, int]) -> str:
    """格式化战利品描述"""
    parts = []

    if resources.get("grain"):
        parts.append(f"粮食 {resources['grain']}")
    if resources.get("silver"):
        parts.append(f"银两 {resources['silver']}")

    if items:
        templates = {
            t.key: t.name
            for t in ItemTemplate.objects.filter(key__in=items.keys()).only("key", "name")
        }
        for key, qty in items.items():
            name = templates.get(key, key)
            parts.append(f"{name} x{qty}")

    return "\n".join(parts) if parts else "无"


def _format_battle_rewards_description(battle_rewards: Dict[str, Any]) -> str:
    """格式化战斗通用奖励描述"""
    if not battle_rewards:
        return ""

    parts = []
    exp_fruit = battle_rewards.get("exp_fruit", 0)
    equipment = battle_rewards.get("equipment", {})

    if exp_fruit > 0:
        parts.append(f"经验果 x{exp_fruit}")

    if equipment:
        templates = {
            t.key: t.name
            for t in ItemTemplate.objects.filter(key__in=equipment.keys()).only("key", "name")
        }
        for key, qty in equipment.items():
            name = templates.get(key, key)
            parts.append(f"{name} x{qty}")

    return "\n".join(parts) if parts else ""


def _format_capture_description(capture_payload: Any) -> str:
    if not isinstance(capture_payload, dict):
        return ""
    name = (capture_payload.get("guest_name") or "").strip()
    if not name:
        return ""
    return f"{name}（已押入监牢，装备尽失）"


def _grant_loot_items(manor: Manor, items: Dict[str, int]) -> None:
    """批量发放掠夺的物品"""
    if not items:
        return

    templates = {
        t.key: t
        for t in ItemTemplate.objects.filter(key__in=items.keys()).only("id", "key")
    }

    if not templates:
        return

    # 逐项 upsert：避免批量写入在并发创建下的 IntegrityError / 丢失更新问题
    for key, qty in items.items():
        if qty <= 0:
            continue
        template = templates.get(key)
        if not template:
            continue
        existing = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=manor,
                template=template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )
        if existing:
            InventoryItem.objects.filter(pk=existing.pk).update(quantity=F("quantity") + int(qty))
        else:
            try:
                InventoryItem.objects.create(
                    manor=manor,
                    template=template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                    quantity=int(qty),
                )
            except IntegrityError:
                # 并发创建时回退到原子性累加
                InventoryItem.objects.filter(
                    manor=manor,
                    template=template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                ).update(quantity=F("quantity") + int(qty))
