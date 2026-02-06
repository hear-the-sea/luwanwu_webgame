from __future__ import annotations

from django.core.paginator import Paginator

from core.utils import safe_int, safe_ordering
from gameplay.services.resources import sync_resource_production

from .services.auction_service import (
    get_active_slots,
    get_auction_stats,
    get_my_bids,
    get_my_leading_bids,
)
from .services.bank_service import get_bank_info
from .services.market_service import (
    expire_user_listings,
    get_active_listings,
    get_my_listings,
    get_tradeable_inventory,
)
from .services.shop_service import (
    EFFECT_TYPE_CATEGORY,
    get_sellable_effect_types,
    get_sellable_inventory,
    get_shop_items_for_display,
)


def get_trade_context(request, manor) -> dict:
    sync_resource_production(manor)
    tab = request.GET.get("tab", "shop")
    context = {
        "current_tab": tab,
        "tabs": [
            {"key": "auction", "name": "拍卖行"},
            {"key": "bank", "name": "钱庄"},
            {"key": "shop", "name": "商店"},
            {"key": "market", "name": "集市"},
        ],
        "manor": manor,
    }

    if tab == "auction":
        context["auction_stats"] = get_auction_stats(manor)
        auction_view = request.GET.get("view", "browse")
        context["auction_view"] = auction_view

        if auction_view == "browse":
            category = request.GET.get("category", "all")
            rarity = request.GET.get("rarity", "all")
            order_by = safe_ordering(
                request.GET.get("order_by", "-current_price"),
                "-current_price",
                {"-current_price", "current_price", "-bid_count", "bid_count"},
            )
            page = safe_int(request.GET.get("page", 1), 1)
            slots = get_active_slots(category=category, rarity=rarity, order_by=order_by)
            paginator = Paginator(slots, 5)
            page_obj = paginator.get_page(page)

            # 使用批量查询优化 N+1 问题
            from trade.services.auction_service import get_slots_bid_info_batch
            slots_list = list(page_obj)
            bid_info_map = get_slots_bid_info_batch(slots_list, manor)
            for slot in slots_list:
                slot.bid_info = bid_info_map.get(slot.id, {})

            context.update(
                {
                    "auction_slots": slots_list,
                    "page_obj": page_obj,
                    "selected_category": category,
                    "selected_rarity": rarity,
                    "selected_order": order_by,
                    "categories": [{"key": "all", "label": "全部"}]
                    + [
                        {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                        for c in sorted(EFFECT_TYPE_CATEGORY.keys())
                    ],
                }
            )
        elif auction_view == "my_bids":
            my_bids = get_my_bids(manor)
            my_leading = get_my_leading_bids(manor)
            # 使用批量查询优化 N+1 问题
            from trade.services.auction_service import get_slots_bid_info_batch
            bid_info_map = get_slots_bid_info_batch(my_leading, manor)
            for slot in my_leading:
                slot.bid_info = bid_info_map.get(slot.id, {})
            context.update(
                {
                    "my_bids": my_bids,
                    "my_leading_slots": my_leading,
                }
            )

    elif tab == "shop":
        def normalize_effect_type(effect_type: str) -> str:
            effect_type = effect_type or "other"
            if effect_type in {"magnifying_glass", "peace_shield", "manor_rename"}:
                return "tool"
            return effect_type

        selected_category = request.GET.get("category", "all")
        if selected_category != "all":
            selected_category = normalize_effect_type(selected_category)
        shop_items = get_shop_items_for_display()
        sellable_items = list(get_sellable_inventory(manor, category=selected_category))

        # 使用 distinct 查询构建分类，避免遍历全部对象
        categories = {"all"}
        categories.update(normalize_effect_type(item.effect_type or "other") for item in shop_items)
        categories.update(get_sellable_effect_types(manor))
        category_options = [{"key": "all", "label": "全部"}] + [
            {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
            for c in sorted(c for c in categories if c and c != "all")
        ]

        # 商店物品筛选（shop_items 是配置数据，数量固定，内存筛选可接受）
        if selected_category != "all":
            shop_items = [
                item
                for item in shop_items
                if normalize_effect_type(item.effect_type or "other") == selected_category
            ]

        context.update(
            {
                "shop_items": shop_items,
                "inventory": sellable_items,
                "categories": category_options,
                "selected_category": selected_category,
            }
        )

    elif tab == "bank":
        context["bank_info"] = get_bank_info(manor)

    elif tab == "market":
        expire_user_listings(manor)
        market_view = request.GET.get("view", "buy")
        context["market_view"] = market_view

        if market_view == "buy":
            category = request.GET.get("category", "all")
            rarity = request.GET.get("rarity", "all")
            order_by = safe_ordering(
                request.GET.get("order_by", "-listed_at"),
                "-listed_at",
                {"-listed_at", "listed_at", "-price", "price", "-expires_at", "expires_at"},
            )
            listings = get_active_listings(order_by=order_by, category=category, rarity=rarity)
            paginator = Paginator(listings, 5)
            page_number = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)
            context.update(
                {
                    "listings": page_obj,
                    "page_obj": page_obj,
                    "selected_category": category,
                    "selected_rarity": rarity,
                    "selected_order": order_by,
                    "categories": [{"key": "all", "label": "全部"}]
                    + [
                        {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                        for c in sorted(EFFECT_TYPE_CATEGORY.keys())
                    ],
                }
            )
        elif market_view == "sell":
            category = request.GET.get("category", "all")
            page = safe_int(request.GET.get("page", 1), 1)

            # 使用数据库筛选代替内存筛选
            tradeable_qs = get_tradeable_inventory(manor)
            if category != "all":
                tool_effect_types = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}
                if category in tool_effect_types:
                    tradeable_qs = tradeable_qs.filter(template__effect_type__in=tool_effect_types)
                else:
                    tradeable_qs = tradeable_qs.filter(template__effect_type=category)

            paginator = Paginator(tradeable_qs, 5)
            page_obj = paginator.get_page(page)
            context.update(
                {
                    "tradeable_items": page_obj,
                    "page_obj": page_obj,
                    "selected_category": category,
                    "categories": [{"key": "all", "label": "全部"}]
                    + [
                        {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                        for c in sorted(EFFECT_TYPE_CATEGORY.keys())
                    ],
                }
            )
        elif market_view == "my_listings":
            status = request.GET.get("status", "all")
            my_listings = get_my_listings(manor, status)
            paginator = Paginator(my_listings, 5)
            page_number = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)
            context.update(
                {
                    "my_listings": page_obj,
                    "page_obj": page_obj,
                    "selected_status": status,
                }
            )

    return context
