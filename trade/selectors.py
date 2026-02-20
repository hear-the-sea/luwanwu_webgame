from __future__ import annotations

from django.core.paginator import Paginator

from core.utils import safe_int, safe_ordering
from gameplay.services.resources import sync_resource_production

from .services.auction_service import get_active_slots, get_auction_stats, get_my_bids, get_my_leading_bids
from .services.bank_service import get_bank_info
from .services.market_service import expire_user_listings, get_active_listings, get_my_listings, get_tradeable_inventory
from .services.shop_service import (
    EFFECT_TYPE_CATEGORY,
    get_sellable_effect_types,
    get_sellable_inventory,
    get_shop_items_for_display,
)

_TOOL_EFFECT_TYPES = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}


def _base_trade_context(tab: str, manor) -> dict:
    return {
        "current_tab": tab,
        "tabs": [
            {"key": "auction", "name": "拍卖行"},
            {"key": "bank", "name": "钱庄"},
            {"key": "shop", "name": "商店"},
            {"key": "market", "name": "集市"},
        ],
        "manor": manor,
    }


def _effect_type_category_options() -> list[dict]:
    return [{"key": "all", "label": "全部"}] + [
        {"key": category_key, "label": EFFECT_TYPE_CATEGORY.get(category_key, category_key)}
        for category_key in sorted(EFFECT_TYPE_CATEGORY.keys())
    ]


def _normalize_effect_type(effect_type: str) -> str:
    normalized_effect_type = effect_type or "other"
    if normalized_effect_type in _TOOL_EFFECT_TYPES:
        return "tool"
    return normalized_effect_type


def _update_auction_browse_context(request, manor, context: dict) -> None:
    category = request.GET.get("category", "all")
    rarity = request.GET.get("rarity", "all")
    order_by = safe_ordering(
        request.GET.get("order_by", "-current_price"),
        "-current_price",
        {"-current_price", "current_price", "-bid_count", "bid_count"},
    )
    page = safe_int(request.GET.get("page", 1), 1)
    slots = get_active_slots(category=category, rarity=rarity, order_by=order_by)
    page_obj = Paginator(slots, 5).get_page(page)

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
            "categories": _effect_type_category_options(),
        }
    )


def _update_auction_my_bids_context(manor, context: dict) -> None:
    my_bids = get_my_bids(manor)
    my_leading = get_my_leading_bids(manor)

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


def _update_auction_context(request, manor, context: dict) -> None:
    context["auction_stats"] = get_auction_stats(manor)
    auction_view = request.GET.get("view", "browse")
    context["auction_view"] = auction_view

    if auction_view == "browse":
        _update_auction_browse_context(request, manor, context)
    elif auction_view == "my_bids":
        _update_auction_my_bids_context(manor, context)


def _build_shop_category_options(shop_items, manor) -> list[dict]:
    categories = {"all"}
    categories.update(_normalize_effect_type(item.effect_type or "other") for item in shop_items)
    categories.update(get_sellable_effect_types(manor))

    return [{"key": "all", "label": "全部"}] + [
        {"key": category_key, "label": EFFECT_TYPE_CATEGORY.get(category_key, category_key)}
        for category_key in sorted(key for key in categories if key and key != "all")
    ]


def _update_shop_context(request, manor, context: dict) -> None:
    selected_category = request.GET.get("category", "all")
    if selected_category != "all":
        selected_category = _normalize_effect_type(selected_category)

    shop_items = get_shop_items_for_display()
    sellable_items = list(get_sellable_inventory(manor, category=selected_category))
    category_options = _build_shop_category_options(shop_items, manor)

    if selected_category != "all":
        shop_items = [
            item for item in shop_items if _normalize_effect_type(item.effect_type or "other") == selected_category
        ]

    context.update(
        {
            "shop_items": shop_items,
            "inventory": sellable_items,
            "categories": category_options,
            "selected_category": selected_category,
        }
    )


def _update_market_buy_context(request, context: dict) -> None:
    category = request.GET.get("category", "all")
    rarity = request.GET.get("rarity", "all")
    order_by = safe_ordering(
        request.GET.get("order_by", "-listed_at"),
        "-listed_at",
        {"-listed_at", "listed_at", "-price", "price", "-expires_at", "expires_at"},
    )
    listings = get_active_listings(order_by=order_by, category=category, rarity=rarity)
    page_obj = Paginator(listings, 5).get_page(request.GET.get("page", 1))

    context.update(
        {
            "listings": page_obj,
            "page_obj": page_obj,
            "selected_category": category,
            "selected_rarity": rarity,
            "selected_order": order_by,
            "categories": _effect_type_category_options(),
        }
    )


def _filter_tradeable_inventory(manor, category: str):
    tradeable_qs = get_tradeable_inventory(manor)
    if category == "all":
        return tradeable_qs

    if category in _TOOL_EFFECT_TYPES:
        return tradeable_qs.filter(template__effect_type__in=_TOOL_EFFECT_TYPES)
    return tradeable_qs.filter(template__effect_type=category)


def _update_market_sell_context(request, manor, context: dict) -> None:
    category = request.GET.get("category", "all")
    page = safe_int(request.GET.get("page", 1), 1)
    tradeable_qs = _filter_tradeable_inventory(manor, category)
    page_obj = Paginator(tradeable_qs, 5).get_page(page)

    context.update(
        {
            "tradeable_items": page_obj,
            "page_obj": page_obj,
            "selected_category": category,
            "categories": _effect_type_category_options(),
        }
    )


def _update_market_my_listings_context(request, manor, context: dict) -> None:
    status = request.GET.get("status", "all")
    my_listings = get_my_listings(manor, status)
    page_obj = Paginator(my_listings, 5).get_page(request.GET.get("page", 1))

    context.update(
        {
            "my_listings": page_obj,
            "page_obj": page_obj,
            "selected_status": status,
        }
    )


def _update_market_context(request, manor, context: dict) -> None:
    expire_user_listings(manor)
    market_view = request.GET.get("view", "buy")
    context["market_view"] = market_view

    if market_view == "buy":
        _update_market_buy_context(request, context)
    elif market_view == "sell":
        _update_market_sell_context(request, manor, context)
    elif market_view == "my_listings":
        _update_market_my_listings_context(request, manor, context)


def get_trade_context(request, manor) -> dict:
    sync_resource_production(manor)
    tab = request.GET.get("tab", "shop")
    context = _base_trade_context(tab, manor)

    if tab == "auction":
        _update_auction_context(request, manor, context)
    elif tab == "shop":
        _update_shop_context(request, manor, context)
    elif tab == "bank":
        context["bank_info"] = get_bank_info(manor)
    elif tab == "market":
        _update_market_context(request, manor, context)

    return context
