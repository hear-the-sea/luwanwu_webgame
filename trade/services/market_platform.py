from __future__ import annotations

from gameplay.models import ResourceEvent
from gameplay.services.inventory.core import add_item_to_inventory_locked
from gameplay.services.resources import grant_resources_locked, spend_resources_locked
from gameplay.services.utils.messages import create_message
from gameplay.services.utils.notifications import notify_user


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


def grant_market_item_locked(locked_manor, *, item_key: str, quantity: int) -> None:
    add_item_to_inventory_locked(locked_manor, item_key, quantity)


def load_market_item_template(item_key: str):
    from gameplay.models import ItemTemplate

    from .market_listing_helpers import load_tradeable_item_template

    return load_tradeable_item_template(item_template_model=ItemTemplate, item_key=item_key)


def lock_market_listing_inventory_item(*, locked_manor, item_template):
    from gameplay.models import InventoryItem

    from .market_listing_helpers import lock_listing_inventory_item

    return lock_listing_inventory_item(
        inventory_item_model=InventoryItem,
        locked_manor=locked_manor,
        item_template=item_template,
    )


def decrement_market_listing_inventory(*, inventory_item, quantity: int) -> None:
    from gameplay.models import InventoryItem

    from .market_listing_helpers import decrement_listing_inventory

    decrement_listing_inventory(
        inventory_item_model=InventoryItem,
        inventory_item=inventory_item,
        quantity=quantity,
    )


def get_tradeable_inventory_queryset(manor):
    from gameplay.models import InventoryItem

    return InventoryItem.objects.filter(
        manor=manor,
        template__tradeable=True,
        quantity__gt=0,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).select_related("template")
