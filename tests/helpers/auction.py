from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Sequence, Tuple

from django.utils import timezone

from gameplay.models import ItemTemplate
from gameplay.services.manor.core import ensure_manor
from trade.models import AuctionBid, AuctionRound, AuctionSlot, FrozenGoldBar
from trade.services import auction_service


def ensure_auction_item_template(key: str) -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key=key,
        defaults={
            "name": "拍卖测试物品",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    return template


def ensure_gold_bar_template() -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key=auction_service.GOLD_BAR_ITEM_KEY,
        defaults={
            "name": "金条",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    return template


def create_auction_round(
    *,
    round_number: int,
    status: AuctionRound.Status = AuctionRound.Status.ACTIVE,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
) -> AuctionRound:
    now = timezone.now()
    start_at = start_at or (now - timedelta(hours=1))
    end_at = end_at or (now + timedelta(hours=1))
    return AuctionRound.objects.create(
        round_number=round_number,
        status=status,
        start_at=start_at,
        end_at=end_at,
    )


def create_auction_slot(
    *,
    auction_round: AuctionRound,
    item_key: str,
    quantity: int = 1,
    starting_price: int = 10,
    current_price: Optional[int] = None,
    min_increment: int = 1,
    status: AuctionSlot.Status = AuctionSlot.Status.ACTIVE,
    slot_index: int = 0,
    config_key: Optional[str] = None,
) -> AuctionSlot:
    current_price = current_price if current_price is not None else starting_price
    template = ensure_auction_item_template(item_key)
    return AuctionSlot.objects.create(
        round=auction_round,
        item_template=template,
        quantity=int(quantity),
        starting_price=starting_price,
        current_price=current_price,
        min_increment=min_increment,
        status=status,
        config_key=config_key or template.key,
        slot_index=slot_index,
    )


def create_round_and_slot(
    *,
    item_key: str,
    round_number: int,
    round_status: AuctionRound.Status = AuctionRound.Status.ACTIVE,
    slot_status: AuctionSlot.Status = AuctionSlot.Status.ACTIVE,
    quantity: int = 1,
    starting_price: int = 10,
    current_price: Optional[int] = None,
    min_increment: int = 1,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    slot_index: int = 0,
    config_key: Optional[str] = None,
) -> Tuple[AuctionRound, AuctionSlot]:
    auction_round = create_auction_round(
        round_number=round_number,
        status=round_status,
        start_at=start_at,
        end_at=end_at,
    )
    slot = create_auction_slot(
        auction_round=auction_round,
        item_key=item_key,
        quantity=quantity,
        starting_price=starting_price,
        current_price=current_price,
        min_increment=min_increment,
        status=slot_status,
        slot_index=slot_index,
        config_key=config_key,
    )
    return auction_round, slot


def create_active_round_slot(
    *,
    item_key: str,
    quantity: int = 1,
    round_number: int = 20001,
    starting_price: int = 2,
    min_increment: int = 1,
) -> AuctionSlot:
    _, slot = create_round_and_slot(
        item_key=item_key,
        round_number=round_number,
        quantity=quantity,
        starting_price=starting_price,
        current_price=starting_price,
        min_increment=min_increment,
    )
    return slot


@dataclass(frozen=True)
class AuctionSlotBidSpec:
    username: str
    amount: int
    status: AuctionBid.Status = AuctionBid.Status.ACTIVE
    frozen_amount: Optional[int] = None
    create_frozen: bool = True


@dataclass
class AuctionSlotWithBids:
    auction_round: AuctionRound
    slot: AuctionSlot
    bids: list[AuctionBid]
    users_by_username: Dict[str, Any]
    manors_by_username: Dict[str, Any]


def create_slot_with_bids(
    *,
    django_user_model: Any,
    bid_specs: Sequence[AuctionSlotBidSpec],
    item_key: str,
    round_number: int,
    round_status: AuctionRound.Status = AuctionRound.Status.ACTIVE,
    slot_status: AuctionSlot.Status = AuctionSlot.Status.ACTIVE,
    quantity: int = 1,
    starting_price: int = 10,
    current_price: Optional[int] = None,
    min_increment: int = 1,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
    slot_index: int = 0,
    config_key: Optional[str] = None,
) -> AuctionSlotWithBids:
    if not bid_specs:
        raise ValueError("bid_specs must contain at least one entry")

    auction_round, slot = create_round_and_slot(
        item_key=item_key,
        round_number=round_number,
        round_status=round_status,
        slot_status=slot_status,
        quantity=quantity,
        starting_price=starting_price,
        current_price=current_price,
        min_increment=min_increment,
        start_at=start_at,
        end_at=end_at,
        slot_index=slot_index,
        config_key=config_key,
    )

    bids: list[AuctionBid] = []
    users_by_username: Dict[str, Any] = {}
    manors_by_username: Dict[str, Any] = {}

    for spec in bid_specs:
        user = django_user_model.objects.create_user(username=spec.username, password="pass123")
        manor = ensure_manor(user)
        bid = AuctionBid.objects.create(
            slot=slot,
            manor=manor,
            amount=spec.amount,
            status=spec.status,
            frozen_gold_bars=spec.amount,
        )
        if spec.create_frozen:
            frozen_amount = spec.frozen_amount if spec.frozen_amount is not None else spec.amount
            FrozenGoldBar.objects.create(
                manor=manor,
                amount=frozen_amount,
                reason=FrozenGoldBar.Reason.AUCTION_BID,
                auction_bid=bid,
                is_frozen=True,
            )

        bids.append(bid)
        users_by_username[spec.username] = user
        manors_by_username[spec.username] = manor

    return AuctionSlotWithBids(
        auction_round=auction_round,
        slot=slot,
        bids=bids,
        users_by_username=users_by_username,
        manors_by_username=manors_by_username,
    )
