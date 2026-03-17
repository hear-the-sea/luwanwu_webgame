"""Raid combat configuration and deterministic patch points."""

from __future__ import annotations

import random

from ....constants import PVPConstants

# Small inventories are sampled in-memory to preserve legacy shuffle semantics.
LOOT_ITEM_SMALL_INVENTORY_THRESHOLD = 200
# Large inventories are scanned in batches to avoid full-table iteration.
LOOT_ITEM_SAMPLE_BATCH_SIZE = 200
# Hard cap on batch iterations so pathological inventories do not scan forever.
LOOT_ITEM_SAMPLE_MAX_BATCHES = 6

__all__ = [
    "random",
    "PVPConstants",
    "LOOT_ITEM_SMALL_INVENTORY_THRESHOLD",
    "LOOT_ITEM_SAMPLE_BATCH_SIZE",
    "LOOT_ITEM_SAMPLE_MAX_BATCHES",
]
