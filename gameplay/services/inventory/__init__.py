"""
Inventory services (split from the former monolithic inventory.py).

We keep `gameplay.services.inventory` as the public import surface for backward
compatibility. Submodules:
  - core: CRUD / locking helpers for inventory rows
  - use: item effect application (warehouse-use items + guest-target items)
"""

from __future__ import annotations

# NOTE: tests monkeypatch `gameplay.services.inventory.random.random`.
# Keep `random` as a package attribute and make effect code reference it.
import random  # noqa: F401

from .core import (
    GRAIN_ITEM_KEY,
    ItemEffectHandler,
    add_item_to_inventory,
    add_item_to_inventory_locked,
    consume_inventory_item,
    consume_inventory_item_for_manor_locked,
    consume_inventory_item_locked,
    get_item_quantity,
    list_inventory_items,
    sync_manor_grain,
)
from .use import (
    ITEM_EFFECT_HANDLERS,
    NON_WAREHOUSE_MESSAGES,
    use_guest_rebirth_card,
    use_inventory_item,
    use_xidianka,
    use_xisuidan,
)

__all__ = [
    "random",
    "GRAIN_ITEM_KEY",
    "ItemEffectHandler",
    "add_item_to_inventory_locked",
    "add_item_to_inventory",
    "consume_inventory_item_locked",
    "consume_inventory_item_for_manor_locked",
    "consume_inventory_item",
    "sync_manor_grain",
    "list_inventory_items",
    "get_item_quantity",
    "NON_WAREHOUSE_MESSAGES",
    "ITEM_EFFECT_HANDLERS",
    "use_inventory_item",
    "use_guest_rebirth_card",
    "use_xisuidan",
    "use_xidianka",
]
