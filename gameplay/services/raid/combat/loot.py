"""Raid loot calculation/apply helpers (split from legacy combat.py)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from django.db import IntegrityError
from django.db.models import F

from gameplay.services.raid import combat as combat_pkg

from ....models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from ...resources import log_resource_gain


def _normalize_mapping(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _coerce_positive_int(raw: Any, default: int = 0) -> int:
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else 0


def _normalize_positive_int_mapping(raw: Any) -> Dict[str, int]:
    data = _normalize_mapping(raw)
    normalized: Dict[str, int] = {}
    for key, value in data.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized_value = _coerce_positive_int(value, 0)
        if normalized_value > 0:
            normalized[normalized_key] = normalized_value
    return normalized


def _calculate_resource_loot(defender: Manor, loot_percent: float) -> Dict[str, int]:
    loot_resources: Dict[str, int] = {}

    if defender.grain > 0:
        loot_grain = min(int(defender.grain * loot_percent), 10000)
        if loot_grain > 0:
            loot_resources["grain"] = loot_grain

    if defender.silver > 0:
        loot_silver = min(int(defender.silver * loot_percent), 10000)
        if loot_silver > 0:
            loot_resources["silver"] = loot_silver

    return loot_resources


def _build_loot_item_queryset(defender: Manor):
    return InventoryItem.objects.filter(
        manor=defender,
        template__tradeable=True,
        quantity__gt=0,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


def _parse_loot_candidate(row: Dict[str, Any], loot_items: Dict[str, int]) -> Tuple[str, int, float] | None:
    quantity = int(row.get("quantity", 0) or 0)
    if quantity <= 0:
        return None

    template_key = row.get("template__key")
    if not template_key:
        return None
    template_key = str(template_key)
    if template_key in loot_items:
        return None

    rarity = row.get("template__rarity") or "gray"
    if not isinstance(rarity, str):
        rarity = str(rarity)

    rarity_mult = combat_pkg.PVPConstants.RARITY_LOOT_MULTIPLIER.get(rarity, 1.0)
    loot_chance = combat_pkg.PVPConstants.LOOT_ITEM_BASE_CHANCE * rarity_mult
    return template_key, quantity, loot_chance


def _roll_loot_quantity(quantity: int) -> int:
    max_qty = min(
        int(quantity * combat_pkg.PVPConstants.LOOT_ITEM_MAX_QUANTITY_PERCENT),
        combat_pkg.PVPConstants.LOOT_ITEM_MAX_QUANTITY,
    )
    loot_qty = combat_pkg.random.randint(1, max(1, max_qty))
    return min(loot_qty, quantity)


def _try_loot_from_row(row: Dict[str, Any], loot_items: Dict[str, int]) -> Tuple[str, int] | None:
    candidate = _parse_loot_candidate(row, loot_items)
    if candidate is None:
        return None

    template_key, quantity, loot_chance = candidate
    if combat_pkg.random.random() >= loot_chance:
        return None

    loot_qty = _roll_loot_quantity(quantity)
    if loot_qty <= 0:
        return None
    return template_key, loot_qty


def _collect_loot_from_rows(
    rows: Iterable[Dict[str, Any]],
    loot_items: Dict[str, int],
    *,
    items_looted: int,
    max_loot_items: int,
) -> int:
    for row in rows:
        if items_looted >= max_loot_items:
            break

        looted = _try_loot_from_row(row, loot_items)
        if looted is None:
            continue

        template_key, loot_qty = looted
        loot_items[template_key] = loot_qty
        items_looted += 1

    return items_looted


def _build_small_inventory_rows(base_qs) -> list[Dict[str, Any]]:
    rows = list(base_qs.values("quantity", "template__key", "template__rarity"))
    combat_pkg.random.shuffle(rows)
    return rows


def _iter_sample_batches(base_qs) -> Iterable[list[Dict[str, Any]]]:
    seen_ids: set[int] = set()
    for _ in range(combat_pkg.LOOT_ITEM_SAMPLE_MAX_BATCHES):
        remaining_qs = base_qs.exclude(id__in=seen_ids) if seen_ids else base_qs
        remaining_count = remaining_qs.count()
        if remaining_count <= 0:
            break

        batch_size = min(combat_pkg.LOOT_ITEM_SAMPLE_BATCH_SIZE, remaining_count)
        max_offset = max(0, remaining_count - batch_size)
        offset = combat_pkg.random.randint(0, max_offset) if max_offset else 0

        batch_rows = list(
            remaining_qs.order_by("id").values("id", "quantity", "template__key", "template__rarity")[
                offset : offset + batch_size
            ]
        )
        if not batch_rows:
            continue

        for row in batch_rows:
            seen_ids.add(int(row["id"]))

        combat_pkg.random.shuffle(batch_rows)
        yield batch_rows


def _calculate_loot_items(base_qs) -> Dict[str, int]:
    loot_items: Dict[str, int] = {}
    items_looted = 0
    max_loot_items = combat_pkg.PVPConstants.LOOT_ITEM_MAX_COUNT

    total_candidates = base_qs.count()
    if total_candidates <= combat_pkg.LOOT_ITEM_SMALL_INVENTORY_THRESHOLD:
        rows = _build_small_inventory_rows(base_qs)
        _collect_loot_from_rows(rows, loot_items, items_looted=items_looted, max_loot_items=max_loot_items)
        return loot_items

    for batch_rows in _iter_sample_batches(base_qs):
        items_looted = _collect_loot_from_rows(
            batch_rows,
            loot_items,
            items_looted=items_looted,
            max_loot_items=max_loot_items,
        )
        if items_looted >= max_loot_items:
            break

    return loot_items


def _calculate_loot(defender: Manor) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    计算战利品。

    Returns:
        (掠夺的资源, 掠夺的物品)
    """
    loot_percent = combat_pkg.random.uniform(
        combat_pkg.PVPConstants.LOOT_RESOURCE_MIN_PERCENT,
        combat_pkg.PVPConstants.LOOT_RESOURCE_MAX_PERCENT,
    )
    loot_resources = _calculate_resource_loot(defender, loot_percent)
    loot_items = _calculate_loot_items(_build_loot_item_queryset(defender))
    return loot_resources, loot_items


def _apply_loot(
    defender: Manor, loot_resources: Dict[str, int], loot_items: Dict[str, int], locked_manor: Manor | None = None
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    从防守方扣除被掠夺的资源和物品，返回实际扣除量。
    """
    loot_resources = _normalize_positive_int_mapping(loot_resources)
    loot_items = _normalize_positive_int_mapping(loot_items)
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
    resources = _normalize_positive_int_mapping(resources)
    items = _normalize_positive_int_mapping(items)
    parts = []

    if resources.get("grain"):
        parts.append(f"粮食 {resources['grain']}")
    if resources.get("silver"):
        parts.append(f"银两 {resources['silver']}")

    if items:
        templates = {t.key: t.name for t in ItemTemplate.objects.filter(key__in=items.keys()).only("key", "name")}
        for key, qty in items.items():
            name = templates.get(key, key)
            parts.append(f"{name} x{qty}")

    return "\n".join(parts) if parts else "无"


def _format_battle_rewards_description(battle_rewards: Dict[str, Any]) -> str:
    """格式化战斗通用奖励描述"""
    normalized_rewards = _normalize_mapping(battle_rewards)
    if not normalized_rewards:
        return ""

    parts = []
    exp_fruit = _coerce_positive_int(normalized_rewards.get("exp_fruit", 0), 0)
    equipment = _normalize_positive_int_mapping(normalized_rewards.get("equipment"))

    if exp_fruit > 0:
        parts.append(f"经验果 x{exp_fruit}")

    if equipment:
        templates = {t.key: t.name for t in ItemTemplate.objects.filter(key__in=equipment.keys()).only("key", "name")}
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
    items = _normalize_positive_int_mapping(items)
    if not items:
        return

    from core.utils.template_loader import load_templates_by_key

    templates = load_templates_by_key(ItemTemplate, keys=items.keys(), only_fields=["id", "key"])

    if not templates:
        return

    # 逐项 upsert：避免批量写入在并发创建下的 IntegrityError / 丢失更新问题
    for key, qty in items.items():
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
            InventoryItem.objects.filter(pk=existing.pk).update(quantity=F("quantity") + qty)
        else:
            try:
                InventoryItem.objects.create(
                    manor=manor,
                    template=template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                    quantity=qty,
                )
            except IntegrityError:
                # 并发创建时回退到原子性累加
                InventoryItem.objects.filter(
                    manor=manor,
                    template=template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                ).update(quantity=F("quantity") + qty)
