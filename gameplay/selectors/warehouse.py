from __future__ import annotations

from django.core.paginator import Paginator

from core.config import WAREHOUSE
from guests.models import GuestStatus

from ..models import InventoryItem, ItemTemplate
from ..models.items import LEGACY_TOOL_EFFECT_TYPES, get_item_effect_type_label
from ..services import get_treasury_capacity, get_treasury_used_space

# 每页显示的物品数量
WAREHOUSE_PAGE_SIZE = 20
GRAIN_ITEM_KEY = "grain"


def _distinct_effect_types(items):
    """Return distinct effect types without inheriting potentially expensive/invalid ordering."""
    return items.order_by().values_list("template__effect_type", flat=True).distinct()


def _collect_rarity_upgrade_source_keys(manor) -> set[str]:
    """
    Collect rarity-upgrade source template keys from item template payloads.

    Keep config values as a safe fallback so behavior won't break if template data is incomplete.
    """
    source_keys: set[str] = set(WAREHOUSE.RARITY_UPGRADE_SOURCE_TEMPLATE_KEYS)
    payloads = (
        manor.inventory_items.filter(
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity__gt=0,
            template__effect_type=ItemTemplate.EffectType.TOOL,
            template__is_usable=True,
        )
        .values_list("template__effect_payload", flat=True)
        .distinct()
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        if payload.get("action") != "upgrade_guest_rarity":
            continue

        raw_source_keys = payload.get("source_template_keys")
        if isinstance(raw_source_keys, list):
            source_keys.update(str(key).strip() for key in raw_source_keys if str(key).strip())

        target_template_map = payload.get("target_template_map")
        if isinstance(target_template_map, dict):
            source_keys.update(str(key).strip() for key in target_template_map.keys() if str(key).strip())
    return source_keys


def _collect_soul_fusion_requirements(manor) -> tuple[int, set[str]]:
    from gameplay.services.inventory.guest_items import (
        SOUL_FUSION_DEFAULT_ALLOWED_RARITIES,
        SOUL_FUSION_DEFAULT_MIN_LEVEL,
        get_soul_fusion_requirements,
    )

    min_level: int | None = None
    allowed_rarities: set[str] = set()
    payloads = (
        manor.inventory_items.filter(
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity__gt=0,
            template__effect_type=ItemTemplate.EffectType.TOOL,
            template__is_usable=True,
        )
        .values_list("template__effect_payload", flat=True)
        .distinct()
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        if payload.get("action") != "soul_fusion":
            continue
        normalized_min_level, normalized_rarities = get_soul_fusion_requirements(payload)
        if min_level is None:
            min_level = normalized_min_level
        else:
            min_level = min(min_level, normalized_min_level)
        allowed_rarities.update(normalized_rarities)
    return (
        min_level or SOUL_FUSION_DEFAULT_MIN_LEVEL,
        allowed_rarities or set(SOUL_FUSION_DEFAULT_ALLOWED_RARITIES),
    )


def _build_projected_grain_item(manor):
    grain_template = ItemTemplate.objects.filter(key=GRAIN_ITEM_KEY).first()
    if not grain_template:
        return None

    projected_item = InventoryItem(
        manor=manor,
        template=grain_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        quantity=0,
    )
    projected_item.display_quantity = max(0, int(getattr(manor, "grain", 0) or 0))
    projected_item.is_projected = True
    projected_item.projected_display_hint = "实时产出待后台同步，当前不可操作"
    return projected_item


def _project_warehouse_grain_item(items, manor, *, current_tab: str, selected_category: str):
    items_list = list(items)
    if current_tab != "warehouse":
        return items_list, None

    projected_grain = max(0, int(getattr(manor, "grain", 0) or 0))
    grain_item = next((item for item in items_list if item.template.key == GRAIN_ITEM_KEY), None)
    if grain_item is None and projected_grain > 0:
        projected_item = _build_projected_grain_item(manor)
        if projected_item is not None:
            effect_type = projected_item.template.effect_type
            if selected_category in {"all", effect_type}:
                items_list.append(projected_item)
                items_list.sort(key=lambda item: (item.template.name, item.id or 0))
                grain_item = projected_item

    if grain_item is None:
        return items_list, None

    actual_quantity = max(0, int(getattr(grain_item, "quantity", 0) or 0))
    grain_item.display_quantity = projected_grain
    grain_item.is_projected = projected_grain != actual_quantity or not getattr(grain_item, "pk", None)
    if grain_item.is_projected:
        grain_item.projected_display_hint = "实时产出待后台同步，当前不可操作"
    return items_list, grain_item


def _append_missing_category_option(
    categories: list[dict], *, effect_type: str | None, tool_effect_types, tool_category_key
):
    key = effect_type or "other"
    if key in tool_effect_types:
        if not any(item["key"] == tool_category_key for item in categories):
            categories.append({"key": tool_category_key, "label": "道具"})
        return
    if not any(item["key"] == key for item in categories):
        categories.append({"key": key, "label": get_item_effect_type_label(key)})


def get_warehouse_context(manor, current_tab: str, selected_category: str, page: int = 1) -> dict:
    # Get frozen gold bars for display adjustment
    from trade.services.auction_service import get_frozen_gold_bars

    context = {
        "manor": manor,
        "frozen_gold_bars": get_frozen_gold_bars(manor),
        "current_tab": current_tab,
    }

    # Load eligible guests once, then derive specific lists in memory to avoid repeated DB queries.
    eligible_guests = list(
        manor.guests.select_related("template")
        .filter(status__in=[GuestStatus.IDLE, GuestStatus.INJURED])
        .order_by("-level", "template__name", "id")
    )
    context["guests_for_rebirth"] = eligible_guests

    guests_for_xisuidan = [guest for guest in eligible_guests if guest.level == 100 and guest.xisuidan_used < 10]
    guests_for_xisuidan.sort(key=lambda guest: (guest.xisuidan_used, guest.template.name, guest.id))
    context["guests_for_xisuidan"] = guests_for_xisuidan

    context["guests_for_xidianka"] = [
        guest
        for guest in eligible_guests
        if (
            guest.allocated_force != 0
            or guest.allocated_intellect != 0
            or guest.allocated_defense != 0
            or guest.allocated_agility != 0
        )
    ]
    from gameplay.services.inventory.guest_items import guest_is_eligible_for_soul_fusion

    soul_fusion_min_level, soul_fusion_allowed_rarities = _collect_soul_fusion_requirements(manor)
    context["guests_for_soul_fusion"] = [
        guest
        for guest in eligible_guests
        if guest_is_eligible_for_soul_fusion(
            guest,
            min_level=soul_fusion_min_level,
            allowed_rarities=soul_fusion_allowed_rarities,
        )
    ]
    rarity_upgrade_source_keys = _collect_rarity_upgrade_source_keys(manor)
    context["guests_for_rarity_upgrade"] = [
        guest
        for guest in eligible_guests
        if guest.status == GuestStatus.IDLE and guest.template.key in rarity_upgrade_source_keys
    ]

    tool_effect_types = LEGACY_TOOL_EFFECT_TYPES
    tool_category_key = "tool"
    if selected_category == "tools":  # 兼容旧参数
        selected_category = tool_category_key

    if current_tab == "treasury":
        items = (
            manor.inventory_items.filter(storage_location=InventoryItem.StorageLocation.TREASURY, quantity__gt=0)
            .select_related("template")
            .order_by("template__name")
        )

        treasury_capacity = get_treasury_capacity(manor)
        treasury_used = get_treasury_used_space(manor)
        context["treasury_capacity"] = treasury_capacity
        context["treasury_used"] = treasury_used
        context["treasury_remaining"] = treasury_capacity - treasury_used
    else:
        items = (
            manor.inventory_items.filter(storage_location=InventoryItem.StorageLocation.WAREHOUSE, quantity__gt=0)
            .select_related("template")
            .order_by("template__name")
        )

    all_items = items
    if selected_category != "all":
        if selected_category in tool_effect_types:
            selected_category = tool_category_key
            items = items.filter(template__effect_type__in=tool_effect_types)
        else:
            items = items.filter(template__effect_type=selected_category)

    # 使用 values + distinct 只查询 effect_type，避免加载全部对象
    # 并清除既有排序，避免 PostgreSQL 下 DISTINCT + 非选择列 ORDER BY 的兼容性问题。
    effect_types = _distinct_effect_types(all_items)

    categories = []
    has_tools = False
    for effect_type in effect_types:
        key = effect_type or "other"
        if key in tool_effect_types:
            has_tools = True
            continue
        label = get_item_effect_type_label(key)
        categories.append({"key": key, "label": label})
    if has_tools:
        categories.append({"key": tool_category_key, "label": "道具"})

    frozen_gold = context["frozen_gold_bars"] if current_tab == "warehouse" else 0

    # 分页处理
    projected_items, projected_grain_item = _project_warehouse_grain_item(
        items,
        manor,
        current_tab=current_tab,
        selected_category=selected_category,
    )
    if projected_grain_item is not None:
        _append_missing_category_option(
            categories,
            effect_type=projected_grain_item.template.effect_type,
            tool_effect_types=tool_effect_types,
            tool_category_key=tool_category_key,
        )
    categories.sort(key=lambda x: x["label"])

    paginator = Paginator(projected_items, WAREHOUSE_PAGE_SIZE)
    page_obj = paginator.get_page(page)
    items_list = list(page_obj)

    for item in items_list:
        if item.template.key == GRAIN_ITEM_KEY:
            item.display_quantity = max(0, int(getattr(manor, "grain", 0) or 0))
        elif item.template.key == "gold_bar" and frozen_gold > 0:
            item.display_quantity = max(0, item.quantity - frozen_gold)
        else:
            item.display_quantity = item.quantity

    context["inventory_items"] = items_list
    context["categories"] = categories
    context["selected_category"] = selected_category

    # 分页信息
    context["pagination"] = {
        "page": page_obj.number,
        "total_pages": paginator.num_pages,
        "total_count": paginator.count,
        "has_previous": page_obj.has_previous(),
        "has_next": page_obj.has_next(),
        "previous_page": page_obj.previous_page_number() if page_obj.has_previous() else None,
        "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
    }

    return context
