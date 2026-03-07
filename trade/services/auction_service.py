"""Auction service public API.

This module is the public compatibility layer.

Internally, the implementation is split into smaller modules under
`trade.services.auction`, but we keep thin wrappers here to preserve backwards
compatibility for:

- direct imports from `trade.services.auction_service`
- unit tests that monkeypatch internal helpers (e.g. `_settle_slot`)
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from gameplay.models import Manor
from trade.models import AuctionBid, AuctionRound
from trade.services.auction.bidding import _notify_outbid_vickrey as _default_notify_outbid_vickrey
from trade.services.auction.bidding import (  # noqa: F401
    get_cutoff_price,
    get_my_rank,
    get_slot_ranking,
    is_in_winning_range,
    validate_bid_amount,
)
from trade.services.auction.constants import (  # noqa: F401
    ALLOWED_AUCTION_ORDER_BY,
    AUCTION_CREATE_LOCK_KEY,
    AUCTION_CREATE_LOCK_TIMEOUT,
    AUCTION_SETTLE_LOCK_KEY,
    AUCTION_SETTLE_LOCK_TIMEOUT,
    GOLD_BAR_ITEM_KEY,
)
from trade.services.auction.gold_bars import (  # noqa: F401
    consume_frozen_gold_bars,
    freeze_gold_bars,
    get_available_gold_bars,
    get_frozen_gold_bars,
    get_total_gold_bars,
    try_get_frozen_record,
    unfreeze_gold_bars,
)
from trade.services.auction.rounds import _settle_slot as _default_settle_slot
from trade.services.auction.rounds import create_auction_round as _create_auction_round_impl
from trade.services.auction.rounds import get_current_round, get_next_round_number  # noqa: F401
from trade.services.auction.rounds import settle_auction_round as _settle_auction_round_impl
from trade.services.auction.selectors import (  # noqa: F401
    get_active_slots,
    get_auction_stats,
    get_my_bids,
    get_my_leading_bids,
    get_my_safe_slots_count,
    get_slot_bid_info,
    get_slots_bid_info_batch,
)
from trade.services.auction_config import get_auction_settings, get_enabled_auction_items

# These are intentionally module globals so tests can monkeypatch them via
# `monkeypatch.setattr(trade.services.auction_service, ...)`.
_settle_slot = _default_settle_slot
_notify_outbid_vickrey = _default_notify_outbid_vickrey


def create_auction_round() -> Optional[AuctionRound]:
    """Create a new auction round if no active/settling rounds exist."""
    return _create_auction_round_impl(
        get_settings_func=get_auction_settings,
        get_enabled_items_func=get_enabled_auction_items,
    )


def place_bid(manor: Manor, slot_id: int, amount: int) -> Tuple[AuctionBid, bool]:
    """Player bid wrapper that preserves monkeypatchability for notifications."""
    from trade.services.auction.bidding import place_bid as _place_bid

    return _place_bid(manor, slot_id, amount, notify_outbid_func=_notify_outbid_vickrey)


def settle_auction_round(round_id: int = None) -> Dict:
    """Settle an auction round with a monkeypatchable slot settlement helper."""
    return _settle_auction_round_impl(round_id=round_id, settle_slot_func=_settle_slot)


__all__ = [
    "ALLOWED_AUCTION_ORDER_BY",
    "AUCTION_CREATE_LOCK_KEY",
    "AUCTION_CREATE_LOCK_TIMEOUT",
    "AUCTION_SETTLE_LOCK_KEY",
    "AUCTION_SETTLE_LOCK_TIMEOUT",
    "GOLD_BAR_ITEM_KEY",
    "_notify_outbid_vickrey",
    "_settle_slot",
    "consume_frozen_gold_bars",
    "create_auction_round",
    "freeze_gold_bars",
    "get_auction_settings",
    "get_active_slots",
    "get_auction_stats",
    "get_available_gold_bars",
    "get_current_round",
    "get_cutoff_price",
    "get_enabled_auction_items",
    "get_frozen_gold_bars",
    "get_my_bids",
    "get_my_leading_bids",
    "get_my_rank",
    "get_my_safe_slots_count",
    "get_next_round_number",
    "get_slot_bid_info",
    "get_slot_ranking",
    "get_slots_bid_info_batch",
    "get_total_gold_bars",
    "is_in_winning_range",
    "place_bid",
    "settle_auction_round",
    "try_get_frozen_record",
    "unfreeze_gold_bars",
    "validate_bid_amount",
]
