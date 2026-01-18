from __future__ import annotations

from guests.models import GuestStatus

from ..models import InventoryItem
from ..services import get_treasury_capacity, get_treasury_used_space


def get_warehouse_context(manor, current_tab: str, selected_category: str) -> dict:
    # Get frozen gold bars for display adjustment
    from trade.services.auction_service import get_frozen_gold_bars

    context = {
        "manor": manor,
        "frozen_gold_bars": get_frozen_gold_bars(manor),
        "current_tab": current_tab,
    }

    guests_for_rebirth = manor.guests.select_related("template").filter(
        status__in=[GuestStatus.IDLE, GuestStatus.INJURED]
    ).order_by("-level", "template__name")
    context["guests_for_rebirth"] = list(guests_for_rebirth)

    guests_for_xisuidan = manor.guests.select_related("template").filter(
        status__in=[GuestStatus.IDLE, GuestStatus.INJURED],
        level=100,
        xisuidan_used__lt=10
    ).order_by("xisuidan_used", "template__name")
    context["guests_for_xisuidan"] = list(guests_for_xisuidan)

    guests_for_xidianka = manor.guests.select_related("template").filter(
        status__in=[GuestStatus.IDLE, GuestStatus.INJURED],
    ).exclude(
        allocated_force=0,
        allocated_intellect=0,
        allocated_defense=0,
        allocated_agility=0,
    ).order_by("-level", "template__name")
    context["guests_for_xidianka"] = list(guests_for_xidianka)

    tool_effect_types = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}
    tool_category_key = "tool"
    if selected_category == "tools":  # 兼容旧参数
        selected_category = tool_category_key

    if current_tab == "treasury":
        items = manor.inventory_items.filter(
            storage_location=InventoryItem.StorageLocation.TREASURY,
            quantity__gt=0
        ).select_related("template").order_by("template__name")

        treasury_capacity = get_treasury_capacity(manor)
        treasury_used = get_treasury_used_space(manor)
        context["treasury_capacity"] = treasury_capacity
        context["treasury_used"] = treasury_used
        context["treasury_remaining"] = treasury_capacity - treasury_used
    else:
        items = manor.inventory_items.filter(
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity__gt=0
        ).select_related("template").order_by("template__name")

    all_items = items
    if selected_category != "all":
        if selected_category in tool_effect_types:
            selected_category = tool_category_key
            items = items.filter(template__effect_type__in=tool_effect_types)
        else:
            items = items.filter(template__effect_type=selected_category)

    categories = []
    seen = set()
    has_tools = False
    for entry in all_items:
        key = entry.template.effect_type or "other"
        if key in tool_effect_types:
            has_tools = True
            continue
        label = entry.category_display or key
        if key not in seen:
            seen.add(key)
            categories.append({"key": key, "label": label})
    if has_tools:
        categories.append({"key": tool_category_key, "label": "道具"})
    categories.sort(key=lambda x: x["label"])

    frozen_gold = context["frozen_gold_bars"] if current_tab == "warehouse" else 0
    items_list = list(items)
    for item in items_list:
        if item.template.key == "gold_bar" and frozen_gold > 0:
            item.display_quantity = max(0, item.quantity - frozen_gold)
        else:
            item.display_quantity = item.quantity

    context["inventory_items"] = items_list
    context["categories"] = categories
    context["selected_category"] = selected_category
    return context
