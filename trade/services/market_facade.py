from __future__ import annotations

from typing import Any

from .market_runtime import expire_listings_queryset_entry, send_purchase_notifications_entry


def create_listing_entry(
    manor: Any,
    item_key: str,
    quantity: int,
    unit_price: int,
    duration: int,
    *,
    commands_module: Any,
    service_module: Any,
) -> Any:
    return commands_module.create_market_listing(
        manor,
        item_key,
        quantity,
        unit_price,
        duration,
        normalize_listing_inputs=getattr(service_module, "normalize_listing_inputs"),
        listing_fees=getattr(service_module, "LISTING_FEES"),
        load_market_item_template=getattr(service_module, "load_market_item_template"),
        validate_listing_price=getattr(service_module, "validate_listing_price"),
        manor_model=getattr(service_module, "Manor"),
        get_listing_fee=getattr(service_module, "get_listing_fee"),
        charge_listing_fee=getattr(service_module, "charge_listing_fee"),
        lock_market_listing_inventory_item=getattr(service_module, "lock_market_listing_inventory_item"),
        get_frozen_gold_bars=__import__(
            "trade.services.auction_service",
            fromlist=["get_frozen_gold_bars"],
        ).get_frozen_gold_bars,
        validate_gold_bar_availability=getattr(service_module, "validate_gold_bar_availability"),
        validate_listing_inventory=getattr(service_module, "validate_listing_inventory"),
        decrement_market_listing_inventory=getattr(service_module, "decrement_market_listing_inventory"),
        validate_listing_total_price=getattr(service_module, "validate_listing_total_price"),
        create_listing_record=getattr(service_module, "create_listing_record"),
        market_listing_model=getattr(service_module, "MarketListing"),
        max_total_price=getattr(service_module, "MAX_TOTAL_PRICE"),
        safe_int=getattr(service_module, "_safe_int"),
    )


def get_active_listings_entry(
    *,
    item_template_id: int | None,
    order_by: str,
    category: str | None,
    rarity: str | None,
    queries_module: Any,
    service_module: Any,
):
    return queries_module.get_active_listings_queryset(
        market_listing_model=getattr(service_module, "MarketListing"),
        now=getattr(service_module, "timezone").now(),
        order_by=order_by,
        allowed_order_by=getattr(service_module, "ALLOWED_LISTING_ORDER_BY"),
        legacy_tool_effect_types=getattr(service_module, "LEGACY_TOOL_EFFECT_TYPES"),
        item_template_id=item_template_id,
        category=category,
        rarity=rarity,
    )


def purchase_listing_entry(buyer: Any, listing_id: int, *, commands_module: Any, service_module: Any) -> Any:
    return commands_module.purchase_market_listing(
        buyer,
        listing_id,
        market_listing_model=getattr(service_module, "MarketListing"),
        market_transaction_model=getattr(service_module, "MarketTransaction"),
        manor_model=getattr(service_module, "Manor"),
        get_locked_listing_for_purchase=getattr(
            service_module, "_market_purchase_helpers"
        ).get_locked_listing_for_purchase,
        validate_listing_for_purchase=getattr(service_module, "_market_purchase_helpers").validate_listing_for_purchase,
        lock_purchase_parties=getattr(service_module, "_market_purchase_helpers").lock_purchase_parties,
        pay_market_purchase=getattr(service_module, "pay_market_purchase"),
        settle_market_sale_proceeds=getattr(service_module, "settle_market_sale_proceeds"),
        grant_listing_item_to_buyer_locked=getattr(
            service_module, "_market_purchase_helpers"
        ).grant_listing_item_to_buyer_locked,
        grant_market_item_locked=getattr(service_module, "grant_market_item_locked"),
        transaction_tax_rate=getattr(service_module, "TRANSACTION_TAX_RATE"),
        send_purchase_notifications=lambda *, buyer, listing, tax_amount, seller_received: send_purchase_notifications_entry(
            buyer=buyer,
            listing=listing,
            tax_amount=tax_amount,
            seller_received=seller_received,
            send_purchase_notifications=getattr(
                service_module, "_market_notification_helpers"
            ).send_purchase_notifications,
            safe_send_market_message=getattr(service_module, "_market_notification_helpers").safe_send_market_message,
            safe_send_market_notification=getattr(
                service_module, "_market_notification_helpers"
            ).safe_send_market_notification,
            create_message_func=getattr(service_module, "send_market_message"),
            notify_user_func=getattr(service_module, "send_market_notification"),
            logger=getattr(service_module, "logger"),
        ),
    )


def cancel_listing_entry(manor: Any, listing_id: int, *, commands_module: Any, service_module: Any) -> dict[str, Any]:
    return commands_module.cancel_market_listing(
        manor,
        listing_id,
        market_listing_model=getattr(service_module, "MarketListing"),
        restore_cancelled_listing_inventory=getattr(
            service_module, "_market_notification_helpers"
        ).restore_cancelled_listing_inventory,
        build_cancel_listing_result=getattr(service_module, "_market_notification_helpers").build_cancel_listing_result,
        grant_market_item_locked=getattr(service_module, "grant_market_item_locked"),
    )


def expire_listings_queryset_entrypoint(
    expired_listings: Any,
    log_label: str,
    *,
    service_module: Any,
    limit: int | None = None,
) -> int:
    return expire_listings_queryset_entry(
        expired_listings,
        log_label,
        expire_listings_queryset_impl=getattr(service_module, "_expire_listings_queryset_impl"),
        market_listing_model=getattr(service_module, "MarketListing"),
        restore_cancelled_listing_inventory=getattr(
            service_module, "_market_notification_helpers"
        ).restore_cancelled_listing_inventory,
        grant_market_item_locked=getattr(service_module, "grant_market_item_locked"),
        create_message_func=getattr(service_module, "send_market_message"),
        notify_user_func=getattr(service_module, "send_market_notification"),
        logger=getattr(service_module, "logger"),
        limit=limit,
    )


def expire_listings_entry(*, limit: int, queries_module: Any, service_module: Any) -> int:
    expired_listings = queries_module.get_expired_listings_queryset(
        market_listing_model=getattr(service_module, "MarketListing"),
        now=getattr(service_module, "timezone").now(),
    )
    return expire_listings_queryset_entrypoint(
        expired_listings,
        "处理过期挂单",
        service_module=service_module,
        limit=limit,
    )


def expire_user_listings_entry(manor: Any, *, queries_module: Any, service_module: Any) -> int:
    expired_listings = queries_module.get_user_expired_listings_queryset(
        market_listing_model=getattr(service_module, "MarketListing"),
        manor=manor,
        now=getattr(service_module, "timezone").now(),
    )
    return expire_listings_queryset_entrypoint(
        expired_listings,
        f"处理用户 {manor.id} 的过期挂单",
        service_module=service_module,
    )


def get_my_listings_entry(manor: Any, *, status: str | None, queries_module: Any, service_module: Any):
    return queries_module.get_my_listings_queryset(
        market_listing_model=getattr(service_module, "MarketListing"),
        manor=manor,
        status=status,
    )


def get_market_stats_entry(*, queries_module: Any, service_module: Any) -> dict[str, int]:
    return queries_module.get_market_stats_payload(
        market_listing_model=getattr(service_module, "MarketListing"),
        market_transaction_model=getattr(service_module, "MarketTransaction"),
        now=getattr(service_module, "timezone").now(),
    )


def get_tradeable_inventory_entry(manor: Any, *, service_module: Any):
    return getattr(service_module, "get_tradeable_inventory_queryset")(manor)
