from __future__ import annotations

import logging
from typing import Any, Callable

from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpRequest

from core.utils import safe_int, safe_ordering
from core.utils.infrastructure import DATABASE_INFRASTRUCTURE_EXCEPTIONS, is_expected_infrastructure_error
from gameplay.models.items import LEGACY_TOOL_EFFECT_TYPES, normalize_item_effect_type
from gameplay.services.technology import get_troop_class_for_key
from trade.services.shop_service import EFFECT_TYPE_CATEGORY

logger = logging.getLogger(__name__)

TRADE_ITEM_PAGE_SIZE = 20
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


def _is_expected_trade_context_error(exc: Exception) -> bool:
    return is_expected_infrastructure_error(
        exc,
        exceptions=DATABASE_INFRASTRUCTURE_EXCEPTIONS,
        allow_runtime_markers=True,
    )


def _safe_call(func: Callable[..., Any], *args: Any, default: Any, log_message: str, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        if not _is_expected_trade_context_error(exc):
            raise
        logger.warning("%s: %s", log_message, exc, exc_info=True)
        return default


def record_trade_issue(context: dict[str, Any], *, section: str, message: str) -> None:
    context.setdefault("trade_alerts", []).append({"section": section, "message": message})


def effect_type_category_options() -> list[dict[str, str]]:
    return [{"key": "all", "label": "全部"}] + [
        {"key": category_key, "label": EFFECT_TYPE_CATEGORY.get(category_key, category_key)}
        for category_key in sorted(EFFECT_TYPE_CATEGORY.keys())
    ]


def normalize_effect_type(effect_type: str | None) -> str:
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


def _iter_sellable_effect_types(sellable_items: Any) -> list[str]:
    if hasattr(sellable_items, "values_list"):
        return list(sellable_items.values_list("template__effect_type", flat=True).distinct())

    effect_types: list[str] = []
    for item in sellable_items:
        effect_type = getattr(getattr(getattr(item, "inventory_item", None), "template", None), "effect_type", "")
        if not effect_type:
            effect_type = getattr(getattr(item, "template", None), "effect_type", "")
        effect_types.append(str(effect_type or ""))
    return effect_types


def _build_shop_category_options(shop_items: Any, sellable_items: Any) -> list[dict[str, str]]:
    categories = {"all"}
    categories.update(normalize_effect_type(item.effect_type or "other") for item in shop_items)
    categories.update(normalize_effect_type(effect_type) for effect_type in _iter_sellable_effect_types(sellable_items))

    return [{"key": "all", "label": "全部"}] + [
        {"key": category_key, "label": EFFECT_TYPE_CATEGORY.get(category_key, category_key)}
        for category_key in sorted(key for key in categories if key and key != "all")
    ]


def _load_sellable_inventory_source(
    manor: Any,
    *,
    get_sellable_inventory: Callable[..., Any],
    get_sellable_inventory_queryset: Callable[..., Any],
    original_get_sellable_inventory: Callable[..., Any],
) -> Any:
    if get_sellable_inventory is not original_get_sellable_inventory:
        return get_sellable_inventory(manor)
    return get_sellable_inventory_queryset(manor)


def _build_inventory_display_rows(
    items: Any, *, build_sellable_inventory_display_rows: Callable[..., Any]
) -> list[Any]:
    item_list = list(items)
    if not item_list:
        return []

    sample = item_list[0]
    if hasattr(sample, "inventory_item") and hasattr(sample, "sell_price"):
        return item_list

    return build_sellable_inventory_display_rows(item_list)


def _filter_tradeable_inventory(
    manor: Any, category: str, *, get_tradeable_inventory: Callable[..., QuerySet[Any]]
) -> Any:
    tradeable_qs = get_tradeable_inventory(manor)
    if category == "all":
        return tradeable_qs

    if category in _TOOL_EFFECT_TYPES:
        return tradeable_qs.filter(template__effect_type__in=_TOOL_EFFECT_TYPES)
    return tradeable_qs.filter(template__effect_type=category)


def build_auction_trade_context(
    request: HttpRequest,
    manor: Any,
    context: dict[str, Any],
    *,
    get_auction_stats: Callable[..., Any],
    get_active_slots: Callable[..., Any],
    get_my_bids: Callable[..., Any],
    get_my_leading_bids: Callable[..., Any],
    get_slots_bid_info_batch: Callable[..., Any],
) -> None:
    context["auction_stats"] = _safe_call(get_auction_stats, manor, default={}, log_message="load auction stats failed")
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
                "categories": effect_type_category_options(),
            }
        )
        return

    if auction_view == "my_bids":
        my_bids = _safe_call(get_my_bids, manor, default=[], log_message="load my auction bids failed")
        my_leading = _safe_call(
            get_my_leading_bids, manor, default=[], log_message="load my leading auction bids failed"
        )
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


def build_shop_trade_context(
    request: HttpRequest,
    manor: Any,
    context: dict[str, Any],
    *,
    get_shop_items_for_display: Callable[..., Any],
    get_sellable_inventory: Callable[..., Any],
    get_sellable_inventory_queryset: Callable[..., Any],
    build_sellable_inventory_display_rows: Callable[..., Any],
    original_get_sellable_inventory: Callable[..., Any],
) -> None:
    shop_view = request.GET.get("view", "buy")
    if shop_view not in {"buy", "sell"}:
        shop_view = "buy"
    selected_category = request.GET.get("category", "all")
    if selected_category != "all":
        selected_category = normalize_effect_type(selected_category)
    buy_page = safe_int(request.GET.get("buy_page", 1), 1, min_val=1)
    sell_page = safe_int(request.GET.get("sell_page", 1), 1, min_val=1)

    shop_items = _safe_call(get_shop_items_for_display, default=[], log_message="load shop items failed")
    sellable_inventory_source = _safe_call(
        _load_sellable_inventory_source,
        manor,
        get_sellable_inventory=get_sellable_inventory,
        get_sellable_inventory_queryset=get_sellable_inventory_queryset,
        original_get_sellable_inventory=original_get_sellable_inventory,
        default=[],
        log_message="load sellable inventory failed",
    )
    category_options = _build_shop_category_options(shop_items, sellable_inventory_source)

    if selected_category != "all":
        shop_items = [
            item for item in shop_items if normalize_effect_type(item.effect_type or "other") == selected_category
        ]

    shop_buy_page_obj = Paginator(shop_items, TRADE_ITEM_PAGE_SIZE).get_page(buy_page)
    shop_sell_page_obj = Paginator(sellable_inventory_source, TRADE_ITEM_PAGE_SIZE).get_page(sell_page)
    inventory_rows = _safe_call(
        _build_inventory_display_rows,
        shop_sell_page_obj.object_list,
        build_sellable_inventory_display_rows=build_sellable_inventory_display_rows,
        default=[],
        log_message="build sellable inventory display failed",
    )

    context.update(
        {
            "shop_view": shop_view,
            "shop_items": list(shop_buy_page_obj.object_list),
            "inventory": inventory_rows,
            "shop_buy_page_obj": shop_buy_page_obj,
            "shop_sell_page_obj": shop_sell_page_obj,
            "categories": category_options,
            "selected_category": selected_category,
        }
    )


def build_market_trade_context(
    request: HttpRequest,
    manor: Any,
    context: dict[str, Any],
    *,
    get_active_listings: Callable[..., Any],
    get_tradeable_inventory: Callable[..., Any],
    get_my_listings: Callable[..., Any],
) -> None:
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
                "categories": effect_type_category_options(),
            }
        )
        return

    if market_view == "sell":
        category = request.GET.get("category", "all")
        if category != "all":
            category = normalize_effect_type(category)
        page = safe_int(request.GET.get("page", 1), 1, min_val=1)
        tradeable_qs = _safe_call(
            _filter_tradeable_inventory,
            manor,
            category,
            get_tradeable_inventory=get_tradeable_inventory,
            default=[],
            log_message="load market sell inventory failed",
        )
        page_obj = Paginator(tradeable_qs, TRADE_ITEM_PAGE_SIZE).get_page(page)
        context.update(
            {
                "tradeable_items": page_obj,
                "page_obj": page_obj,
                "selected_category": category,
                "categories": effect_type_category_options(),
            }
        )
        return

    if market_view == "my_listings":
        status = request.GET.get("status", "all")
        my_listings = _safe_call(
            get_my_listings,
            manor,
            status,
            default=[],
            log_message="load my market listings failed",
        )
        page = safe_int(request.GET.get("page", 1), 1, min_val=1)
        page_obj = Paginator(my_listings, TRADE_ITEM_PAGE_SIZE).get_page(page)
        context.update(
            {
                "my_listings": page_obj,
                "page_obj": page_obj,
                "selected_status": status,
            }
        )


def build_bank_trade_context(
    request: HttpRequest,
    manor: Any,
    context: dict[str, Any],
    *,
    get_bank_info: Callable[..., Any],
    get_troop_bank_capacity: Callable[..., Any],
    get_troop_bank_used_space: Callable[..., Any],
    get_troop_bank_remaining_space: Callable[..., Any],
    get_troop_bank_rows: Callable[..., Any],
) -> None:
    selected_troop_category = (request.GET.get("troop_category") or "all").strip() or "all"
    manor_id = getattr(manor, "id", None)
    context["bank_info"] = _safe_call(
        get_bank_info,
        manor,
        default={
            "gold_bar_base_price": 0,
            "gold_bar_fee_rate": 0,
            "gold_bar_min_price": 0,
            "gold_bar_max_price": 0,
            "current_rate": 0,
            "next_rate": 0,
            "total_cost_per_bar": 0,
            "supply_factor": 0,
            "progressive_factor": 0,
            "effective_supply": 0,
            "pricing_source": "unavailable",
            "pricing_degraded": True,
            "pricing_status_message": "钱庄汇率数据暂时不可用，已暂时关闭兑换。",
            "exchange_available": False,
            "today_count": 0,
            "manor_silver": getattr(manor, "silver", 0),
        },
        log_message=f"load bank info failed: manor_id={manor_id}",
    )
    if context["bank_info"].get("pricing_degraded"):
        record_trade_issue(
            context,
            section="bank",
            message=context["bank_info"].get("pricing_status_message") or "钱庄部分数据暂时不可用。",
        )

    context["troop_bank_capacity"] = _safe_call(
        get_troop_bank_capacity,
        manor,
        default=5000,
        log_message=f"load troop bank capacity failed: manor_id={manor_id}",
    )
    context["troop_bank_used"], context["troop_bank_remaining"] = _safe_call(
        lambda: (get_troop_bank_used_space(manor), get_troop_bank_remaining_space(manor)),
        default=(0, 5000),
        log_message=f"load troop bank usage failed: manor_id={manor_id}",
    )
    troop_bank_rows = _safe_call(
        get_troop_bank_rows,
        manor,
        default=[],
        log_message=f"load troop bank rows failed: manor_id={manor_id}",
    )

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
