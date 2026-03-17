from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gameplay.models import InventoryItem, Manor, Message


def consume_inventory_item_locked(locked_item: InventoryItem, amount: int = 1) -> None:
    from gameplay.services.inventory.core import consume_inventory_item_locked as impl

    impl(locked_item, amount)


def spend_resources(manor: Manor, cost: dict[str, int], note: str, reason: str) -> None:
    from gameplay.services.resources import spend_resources as impl

    impl(manor, cost, note=note, reason=reason)


def create_message(
    manor: Manor,
    kind: str,
    title: str,
    body: str = "",
    battle_report: object | None = None,
    is_read: bool = False,
    attachments: dict[str, Any] | None = None,
) -> Message:
    from gameplay.services.utils.messages import create_message as impl

    return impl(
        manor=manor,
        kind=kind,
        title=title,
        body=body,
        battle_report=battle_report,
        is_read=is_read,
        attachments=attachments,
    )


def notify_user(
    user_id: int,
    payload: dict[str, Any],
    *,
    log_context: str = "WebSocket notification",
) -> bool:
    from gameplay.services.utils.notifications import notify_user as impl

    return impl(user_id, payload, log_context=log_context)


def invalidate_recruitment_hall_cache(manor_id: int) -> None:
    from gameplay.services.utils.cache import invalidate_recruitment_hall_cache as impl

    impl(manor_id)


def get_config_cache_timeout() -> int:
    from gameplay.services.utils.cache import CACHE_TIMEOUT_CONFIG

    return int(CACHE_TIMEOUT_CONFIG)


def get_guest_templates_by_rarity_cache_key() -> str:
    from gameplay.services.utils.cache import CacheKeys

    return str(CacheKeys.GUEST_TEMPLATES_BY_RARITY)


def get_hermit_templates_cache_key() -> str:
    from gameplay.services.utils.cache import CacheKeys

    return str(CacheKeys.HERMIT_TEMPLATES)
