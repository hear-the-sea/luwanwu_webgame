from __future__ import annotations

from django.core.paginator import Paginator

from guests.models import GuestStatus

from ..models import InventoryItem
from ..services import get_treasury_capacity, get_treasury_used_space

# 每页显示的物品数量
WAREHOUSE_PAGE_SIZE = 50


def get_warehouse_context(manor, current_tab: str, selected_category: str, page: int = 1) -> dict:
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

    # 使用 values + distinct 只查询 effect_type，避免加载全部对象
    effect_types = all_items.values_list("template__effect_type", flat=True).distinct()

    category_map = {
        "resource_pack": "资源包",
        "resource": "资源",
        "skill_book": "技能书",
        "experience_items": "经验",
        "medicine": "药品",
        "tool": "道具",
        "equip_helmet": "头盔",
        "equip_armor": "衣服",
        "equip_shoes": "鞋子",
        "equip_weapon": "武器",
        "equip_mount": "坐骑",
        "equip_ornament": "饰品",
        "equip_device": "器械",
    }

    categories = []
    has_tools = False
    for effect_type in effect_types:
        key = effect_type or "other"
        if key in tool_effect_types:
            has_tools = True
            continue
        label = category_map.get(key, "装备" if key.startswith("equip_") else "其他")
        categories.append({"key": key, "label": label})
    if has_tools:
        categories.append({"key": tool_category_key, "label": "道具"})
    categories.sort(key=lambda x: x["label"])

    frozen_gold = context["frozen_gold_bars"] if current_tab == "warehouse" else 0

    # 分页处理
    paginator = Paginator(items, WAREHOUSE_PAGE_SIZE)
    page_obj = paginator.get_page(page)
    items_list = list(page_obj)

    for item in items_list:
        if item.template.key == "gold_bar" and frozen_gold > 0:
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
