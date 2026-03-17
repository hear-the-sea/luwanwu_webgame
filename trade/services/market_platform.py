from __future__ import annotations

from gameplay.models import ResourceEvent

from .trade_platform import create_message, grant_resources_locked, notify_user, spend_resources_locked


def charge_listing_fee(locked_manor, silver_amount: int) -> None:
    spend_resources_locked(
        locked_manor,
        {"silver": silver_amount},
        note="交易行挂单手续费",
        reason=ResourceEvent.Reason.MARKET_LISTING_FEE,
    )


def pay_market_purchase(locked_manor, *, item_name: str, total_price: int) -> None:
    spend_resources_locked(
        locked_manor,
        {"silver": total_price},
        note=f"购买{item_name}",
        reason=ResourceEvent.Reason.MARKET_PURCHASE,
    )


def settle_market_sale_proceeds(locked_manor, *, item_name: str, silver_amount: int) -> None:
    grant_resources_locked(
        locked_manor,
        {"silver": silver_amount},
        note=f"出售{item_name}",
        reason=ResourceEvent.Reason.ITEM_SOLD,
        sync_production=False,
    )


def send_market_message(**kwargs):
    return create_message(**kwargs)


def send_market_notification(user_id: int, payload: dict, *, log_context: str) -> None:
    notify_user(user_id, payload, log_context=log_context)
