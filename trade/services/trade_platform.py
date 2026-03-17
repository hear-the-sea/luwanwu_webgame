from __future__ import annotations


def add_item_to_inventory_locked(*args, **kwargs):
    from gameplay.services.inventory.core import add_item_to_inventory_locked as impl

    return impl(*args, **kwargs)


def consume_inventory_item_for_manor_locked(*args, **kwargs):
    from gameplay.services.inventory.core import consume_inventory_item_for_manor_locked as impl

    return impl(*args, **kwargs)


def get_item_quantity(*args, **kwargs):
    from gameplay.services.inventory.core import get_item_quantity as impl

    return impl(*args, **kwargs)


def grant_resources_locked(*args, **kwargs):
    from gameplay.services.resources import grant_resources_locked as impl

    return impl(*args, **kwargs)


def spend_resources_locked(*args, **kwargs):
    from gameplay.services.resources import spend_resources_locked as impl

    return impl(*args, **kwargs)


def create_message(*args, **kwargs):
    from gameplay.services.utils.messages import create_message as impl

    return impl(*args, **kwargs)


def notify_user(*args, **kwargs):
    from gameplay.services.utils.notifications import notify_user as impl

    return impl(*args, **kwargs)


__all__ = [
    "add_item_to_inventory_locked",
    "consume_inventory_item_for_manor_locked",
    "create_message",
    "get_item_quantity",
    "grant_resources_locked",
    "notify_user",
    "spend_resources_locked",
]
