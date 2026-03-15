from __future__ import annotations

import logging
from typing import Any, Callable

from django.core.paginator import Paginator

from core.utils import safe_int, safe_ordering
from gameplay.models.items import LEGACY_TOOL_EFFECT_TYPES, normalize_item_effect_type
from gameplay.services.manor.troop_bank import (
    get_troop_bank_capacity,
    get_troop_bank_remaining_space,
    get_troop_bank_rows,
    get_troop_bank_used_space,
)
from gameplay.services.resources import sync_resource_production
from gameplay.services.technology import get_troop_class_for_key
from trade.services.auction_service import get_active_slots, get_auction_stats, get_my_bids, get_my_leading_bids
from trade.services.bank_service import get_bank_info
from trade.services.market_service import get_active_listings, get_my_listings, get_tradeable_inventory
from trade.services.shop_service import EFFECT_TYPE_CATEGORY, get_sellable_inventory, get_shop_items_for_display

_TOOL_EFFECT_TYPES = LEGACY_TOOL_EFFECT_TYPES
TRADE_ITEM_PAGE_SIZE = 20
_TROOP_CATEGORY_LABELS: dict[str, str] = {
    "dao": "刀系",
    "qiang": "枪系",
    "jian": "剑系",
    "quan": "拳系",
    "gong": "弓系",
    "scout": "探子",
    "other": "其他",
}
logger = logging.getLogger(__name__)


def _safe_call(func: Callable[..., Any], *args, default: Any, log_message: str, **kwargs) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.warning("%s: %s", log_message, exc, exc_info=True)
        return default


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


def _normalize_effect_type(effect_type: str | None) -> str:
    normalized_effect_type = normalize_item_effect_type(effect_type or "")
    if not normalized_effect_type:
        return "other"
    return normalized_effect_type


def _build_troop_bank_categories(available_classes: set[str]) -> list[dict[str, str]]:
    categories: list[dict[str, str]] = [{"key": "all", "name": "全部"}]
    ordered = ["dao", "qiang", "jian", "quan", "gong", "scout", "other"]
    used = {"all"}

    for class_key in ordered:
        if class_key in available_classes:
            categories.append({"key": class_key, "name": _TROOP_CATEGORY_LABELS.get(class_key, class_key)})
            used.add(class_key)

    for class_key in sorted(available_classes):
        if class_key not in used:
            categories.append({"key": class_key, "name": _TROOP_CATEGORY_LABELS.get(class_key, class_key)})
    return categories


def _update_auction_browse_context(request, manor, context: dict) -> None:
    category = request.GET.get("category", "all")
    rarity = request.GET.get("rarity", "all")
    order_by = safe_ordering(
        request.GET.get("order_by", "-current_price"),
        "-current_price",
        {"-current_price", "current_price", "-bid_count", "bid_count"},
    )
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    slots = _safe_call(
        get_active_slots,
        category=category,
        rarity=rarity,
        order_by=order_by,
        default=[],
        log_message="load active auction slots failed",
    )
    page_obj = Paginator(slots, 5).get_page(page)

    from trade.services.auction_service import get_slots_bid_info_batch

    slots_list = list(page_obj)
    bid_info_map = _safe_call(
        get_slots_bid_info_batch,
        slots_list,
        manor,
        default={},
        log_message="load auction bid info failed",
    )
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
    my_bids = _safe_call(get_my_bids, manor, default=[], log_message="load my auction bids failed")
    my_leading = _safe_call(get_my_leading_bids, manor, default=[], log_message="load my leading auction bids failed")

    from trade.services.auction_service import get_slots_bid_info_batch

    bid_info_map = _safe_call(
        get_slots_bid_info_batch,
        my_leading,
        manor,
        default={},
        log_message="load my leading bid info failed",
    )
    for slot in my_leading:
        slot.bid_info = bid_info_map.get(slot.id, {})

    context.update(
        {
            "my_bids": my_bids,
            "my_leading_slots": my_leading,
        }
    )


def _update_auction_context(request, manor, context: dict) -> None:
    context["auction_stats"] = _safe_call(get_auction_stats, manor, default={}, log_message="load auction stats failed")
    auction_view = request.GET.get("view", "browse")
    context["auction_view"] = auction_view

    if auction_view == "browse":
        _update_auction_browse_context(request, manor, context)
    elif auction_view == "my_bids":
        _update_auction_my_bids_context(manor, context)


def _build_shop_category_options(shop_items, sellable_items) -> list[dict]:
    categories = {"all"}
    categories.update(_normalize_effect_type(item.effect_type or "other") for item in shop_items)
    categories.update(
        _normalize_effect_type(
            getattr(getattr(getattr(item, "inventory_item", None), "template", None), "effect_type", "")
        )
        for item in sellable_items
    )

    return [{"key": "all", "label": "全部"}] + [
        {"key": category_key, "label": EFFECT_TYPE_CATEGORY.get(category_key, category_key)}
        for category_key in sorted(key for key in categories if key and key != "all")
    ]


def _update_shop_context(request, manor, context: dict) -> None:
    shop_view = request.GET.get("view", "buy")
    if shop_view not in {"buy", "sell"}:
        shop_view = "buy"
    selected_category = request.GET.get("category", "all")
    if selected_category != "all":
        selected_category = _normalize_effect_type(selected_category)
    buy_page = safe_int(request.GET.get("buy_page", 1), 1, min_val=1)
    sell_page = safe_int(request.GET.get("sell_page", 1), 1, min_val=1)

    shop_items = _safe_call(get_shop_items_for_display, default=[], log_message="load shop items failed")
    # 买入筛选只作用于买入列表；卖出列表始终展示全部可售物品
    sellable_items = _safe_call(
        lambda: list(get_sellable_inventory(manor)),
        default=[],
        log_message="load sellable inventory failed",
    )
    category_options = _build_shop_category_options(shop_items, sellable_items)

    if selected_category != "all":
        shop_items = [
            item for item in shop_items if _normalize_effect_type(item.effect_type or "other") == selected_category
        ]

    shop_buy_page_obj = Paginator(shop_items, TRADE_ITEM_PAGE_SIZE).get_page(buy_page)
    shop_sell_page_obj = Paginator(sellable_items, TRADE_ITEM_PAGE_SIZE).get_page(sell_page)

    context.update(
        {
            "shop_view": shop_view,
            "shop_items": list(shop_buy_page_obj.object_list),
            "inventory": list(shop_sell_page_obj.object_list),
            "shop_buy_page_obj": shop_buy_page_obj,
            "shop_sell_page_obj": shop_sell_page_obj,
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
    listings = _safe_call(
        get_active_listings,
        order_by=order_by,
        category=category,
        rarity=rarity,
        default=[],
        log_message="load market active listings failed",
    )
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    page_obj = Paginator(listings, TRADE_ITEM_PAGE_SIZE).get_page(page)

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
    if category != "all":
        category = _normalize_effect_type(category)
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    tradeable_qs = _safe_call(
        _filter_tradeable_inventory,
        manor,
        category,
        default=[],
        log_message="load market sell inventory failed",
    )
    page_obj = Paginator(tradeable_qs, TRADE_ITEM_PAGE_SIZE).get_page(page)

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
    my_listings = _safe_call(get_my_listings, manor, status, default=[], log_message="load my market listings failed")
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    page_obj = Paginator(my_listings, TRADE_ITEM_PAGE_SIZE).get_page(page)

    context.update(
        {
            "my_listings": page_obj,
            "page_obj": page_obj,
            "selected_status": status,
        }
    )


def _update_market_context(request, manor, context: dict) -> None:
    market_view = request.GET.get("view", "buy")
    context["market_view"] = market_view

    if market_view == "buy":
        _update_market_buy_context(request, context)
    elif market_view == "sell":
        _update_market_sell_context(request, manor, context)
    elif market_view == "my_listings":
        _update_market_my_listings_context(request, manor, context)


def get_trade_context(request, manor) -> dict:
    _safe_call(
        sync_resource_production,
        manor,
        persist=False,
        default=None,
        log_message=f"sync resource production for trade view failed: manor_id={getattr(manor, 'id', None)}",
    )
    tab = request.GET.get("tab", "shop")
    context = _base_trade_context(tab, manor)

    if tab == "auction":
        _update_auction_context(request, manor, context)
    elif tab == "shop":
        _update_shop_context(request, manor, context)
    elif tab == "bank":
        selected_troop_category = (request.GET.get("troop_category") or "all").strip() or "all"
        manor_id = getattr(manor, "id", None)
        context["bank_info"] = _safe_call(
            get_bank_info,
            manor,
            default={},
            log_message=f"load bank info failed: manor_id={manor_id}",
        )
        context["troop_bank_capacity"] = 5000
        context["troop_bank_used"] = 0
        context["troop_bank_remaining"] = 5000
        context["troop_bank_rows"] = []

        context["troop_bank_capacity"] = _safe_call(
            get_troop_bank_capacity,
            manor,
            default=context["troop_bank_capacity"],
            log_message=f"load troop bank capacity failed: manor_id={manor_id}",
        )
        troop_usage = _safe_call(
            lambda: (get_troop_bank_used_space(manor), get_troop_bank_remaining_space(manor)),
            default=(context["troop_bank_used"], context["troop_bank_remaining"]),
            log_message=f"load troop bank usage failed: manor_id={manor_id}",
        )
        context["troop_bank_used"], context["troop_bank_remaining"] = troop_usage
        context["troop_bank_rows"] = _safe_call(
            get_troop_bank_rows,
            manor,
            default=[],
            log_message=f"load troop bank rows failed: manor_id={manor_id}",
        )

        troop_bank_rows = context.get("troop_bank_rows", [])
        available_classes: set[str] = set()
        for row in troop_bank_rows:
            troop_key = str(row.get("key") or "").strip()
            troop_class = get_troop_class_for_key(troop_key) or "other"
            row["troop_class"] = troop_class
            available_classes.add(troop_class)

        troop_bank_categories = _build_troop_bank_categories(available_classes)
        valid_category_keys = {item["key"] for item in troop_bank_categories}
        if selected_troop_category not in valid_category_keys:
            selected_troop_category = "all"
        if selected_troop_category != "all":
            troop_bank_rows = [row for row in troop_bank_rows if row.get("troop_class") == selected_troop_category]

        context["troop_bank_rows"] = troop_bank_rows
        context["troop_bank_categories"] = troop_bank_categories
        context["troop_bank_current_category"] = selected_troop_category
    elif tab == "market":
        _update_market_context(request, manor, context)

    return context
