from __future__ import annotations

import logging

from django.core.paginator import Paginator

from core.utils import safe_int, safe_ordering
from gameplay.models.items import LEGACY_TOOL_EFFECT_TYPES
from gameplay.services.manor.troop_bank import (
    get_troop_bank_capacity,
    get_troop_bank_remaining_space,
    get_troop_bank_rows,
    get_troop_bank_used_space,
)
from gameplay.services.resources import sync_resource_production
from gameplay.services.technology import get_troop_class_for_key

from .services.auction_service import get_active_slots, get_auction_stats, get_my_bids, get_my_leading_bids
from .services.bank_service import get_bank_info
from .services.market_service import expire_user_listings, get_active_listings, get_my_listings, get_tradeable_inventory
from .services.shop_service import (
    EFFECT_TYPE_CATEGORY,
    get_sellable_effect_types,
    get_sellable_inventory,
    get_shop_items_for_display,
)

_TOOL_EFFECT_TYPES = LEGACY_TOOL_EFFECT_TYPES
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
    try:
        slots = get_active_slots(category=category, rarity=rarity, order_by=order_by)
    except Exception as exc:
        logger.warning("load active auction slots failed: %s", exc, exc_info=True)
        slots = []
    page_obj = Paginator(slots, 5).get_page(page)

    from trade.services.auction_service import get_slots_bid_info_batch

    slots_list = list(page_obj)
    try:
        bid_info_map = get_slots_bid_info_batch(slots_list, manor)
    except Exception as exc:
        logger.warning("load auction bid info failed: %s", exc, exc_info=True)
        bid_info_map = {}
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
    try:
        my_bids = get_my_bids(manor)
    except Exception as exc:
        logger.warning("load my auction bids failed: %s", exc, exc_info=True)
        my_bids = []
    try:
        my_leading = get_my_leading_bids(manor)
    except Exception as exc:
        logger.warning("load my leading auction bids failed: %s", exc, exc_info=True)
        my_leading = []

    from trade.services.auction_service import get_slots_bid_info_batch

    try:
        bid_info_map = get_slots_bid_info_batch(my_leading, manor)
    except Exception as exc:
        logger.warning("load my leading bid info failed: %s", exc, exc_info=True)
        bid_info_map = {}
    for slot in my_leading:
        slot.bid_info = bid_info_map.get(slot.id, {})

    context.update(
        {
            "my_bids": my_bids,
            "my_leading_slots": my_leading,
        }
    )


def _update_auction_context(request, manor, context: dict) -> None:
    try:
        context["auction_stats"] = get_auction_stats(manor)
    except Exception as exc:
        logger.warning("load auction stats failed: %s", exc, exc_info=True)
        context["auction_stats"] = {}
    auction_view = request.GET.get("view", "browse")
    context["auction_view"] = auction_view

    if auction_view == "browse":
        _update_auction_browse_context(request, manor, context)
    elif auction_view == "my_bids":
        _update_auction_my_bids_context(manor, context)


def _build_shop_category_options(shop_items, manor) -> list[dict]:
    categories = {"all"}
    categories.update(_normalize_effect_type(item.effect_type or "other") for item in shop_items)
    try:
        categories.update(get_sellable_effect_types(manor))
    except Exception as exc:
        logger.warning(
            "load sellable effect types failed: manor_id=%s error=%s",
            getattr(manor, "id", None),
            exc,
            exc_info=True,
        )

    return [{"key": "all", "label": "全部"}] + [
        {"key": category_key, "label": EFFECT_TYPE_CATEGORY.get(category_key, category_key)}
        for category_key in sorted(key for key in categories if key and key != "all")
    ]


def _update_shop_context(request, manor, context: dict) -> None:
    selected_category = request.GET.get("category", "all")
    if selected_category != "all":
        selected_category = _normalize_effect_type(selected_category)

    try:
        shop_items = get_shop_items_for_display()
    except Exception as exc:
        logger.warning("load shop items failed: %s", exc, exc_info=True)
        shop_items = []
    try:
        sellable_items = list(get_sellable_inventory(manor, category=selected_category))
    except Exception as exc:
        logger.warning("load sellable inventory failed: %s", exc, exc_info=True)
        sellable_items = []
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
    try:
        listings = get_active_listings(order_by=order_by, category=category, rarity=rarity)
    except Exception as exc:
        logger.warning("load market active listings failed: %s", exc, exc_info=True)
        listings = []
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    page_obj = Paginator(listings, 5).get_page(page)

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
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    try:
        tradeable_qs = _filter_tradeable_inventory(manor, category)
    except Exception as exc:
        logger.warning("load market sell inventory failed: %s", exc, exc_info=True)
        tradeable_qs = []
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
    try:
        my_listings = get_my_listings(manor, status)
    except Exception as exc:
        logger.warning("load my market listings failed: %s", exc, exc_info=True)
        my_listings = []
    page = safe_int(request.GET.get("page", 1), 1, min_val=1)
    page_obj = Paginator(my_listings, 5).get_page(page)

    context.update(
        {
            "my_listings": page_obj,
            "page_obj": page_obj,
            "selected_status": status,
        }
    )


def _update_market_context(request, manor, context: dict) -> None:
    try:
        expire_user_listings(manor)
    except Exception as exc:
        logger.warning(
            "expire user market listings failed: manor_id=%s error=%s", getattr(manor, "id", None), exc, exc_info=True
        )
    market_view = request.GET.get("view", "buy")
    context["market_view"] = market_view

    if market_view == "buy":
        _update_market_buy_context(request, context)
    elif market_view == "sell":
        _update_market_sell_context(request, manor, context)
    elif market_view == "my_listings":
        _update_market_my_listings_context(request, manor, context)


def get_trade_context(request, manor) -> dict:
    try:
        sync_resource_production(manor)
    except Exception as exc:
        logger.warning(
            "sync resource production for trade view failed: manor_id=%s error=%s",
            getattr(manor, "id", None),
            exc,
            exc_info=True,
        )
    tab = request.GET.get("tab", "shop")
    context = _base_trade_context(tab, manor)

    if tab == "auction":
        _update_auction_context(request, manor, context)
    elif tab == "shop":
        _update_shop_context(request, manor, context)
    elif tab == "bank":
        selected_troop_category = (request.GET.get("troop_category") or "all").strip() or "all"
        try:
            context["bank_info"] = get_bank_info(manor)
        except Exception as exc:
            logger.warning(
                "load bank info failed: manor_id=%s error=%s",
                getattr(manor, "id", None),
                exc,
                exc_info=True,
            )
            context["bank_info"] = {}
        context["troop_bank_capacity"] = 5000
        context["troop_bank_used"] = 0
        context["troop_bank_remaining"] = 5000
        context["troop_bank_rows"] = []

        try:
            context["troop_bank_capacity"] = get_troop_bank_capacity(manor)
        except Exception as exc:
            logger.warning(
                "load troop bank capacity failed: manor_id=%s error=%s",
                getattr(manor, "id", None),
                exc,
                exc_info=True,
            )

        try:
            context["troop_bank_used"] = get_troop_bank_used_space(manor)
            context["troop_bank_remaining"] = get_troop_bank_remaining_space(manor)
        except Exception as exc:
            logger.warning(
                "load troop bank usage failed: manor_id=%s error=%s",
                getattr(manor, "id", None),
                exc,
                exc_info=True,
            )

        try:
            context["troop_bank_rows"] = get_troop_bank_rows(manor)
        except Exception as exc:
            logger.warning(
                "load troop bank rows failed: manor_id=%s error=%s",
                getattr(manor, "id", None),
                exc,
                exc_info=True,
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
