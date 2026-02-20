"""Read-only selector helpers for auction service."""

from __future__ import annotations

from typing import Dict, List

from django.db.models import QuerySet

from gameplay.models import Manor
from trade.models import AuctionBid, AuctionSlot

from .bidding import get_cutoff_price, get_slot_ranking, is_in_winning_range
from .constants import ALLOWED_AUCTION_ORDER_BY
from .gold_bars import get_available_gold_bars, get_frozen_gold_bars
from .rounds import get_current_round


def get_active_slots(
    category: str = None,
    rarity: str = None,
    order_by: str = "-current_price",
) -> QuerySet:
    """获取当前活跃的拍卖位列表。"""
    current_round = get_current_round()
    if not current_round:
        return AuctionSlot.objects.none()

    queryset = (
        AuctionSlot.objects.filter(round=current_round, status=AuctionSlot.Status.ACTIVE)
        .select_related("item_template", "highest_bidder", "round")
    )

    if category and category != "all":
        tool_effect_types = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}
        if category in tool_effect_types:
            queryset = queryset.filter(item_template__effect_type__in=tool_effect_types)
        else:
            queryset = queryset.filter(item_template__effect_type=category)

    if rarity and rarity != "all":
        queryset = queryset.filter(item_template__rarity=rarity)

    if not order_by or not isinstance(order_by, str):
        order_by = "-current_price"
    else:
        order_by = order_by.strip()
        if order_by.startswith("-"):
            field = order_by[1:]
            if field not in ALLOWED_AUCTION_ORDER_BY:
                order_by = "-current_price"
            else:
                order_by = f"-{field}"
        else:
            if order_by not in ALLOWED_AUCTION_ORDER_BY:
                order_by = "-current_price"

    return queryset.order_by(order_by)


def get_my_bids(manor: Manor, include_history: bool = False) -> QuerySet:
    """获取我的出价记录。"""
    queryset = AuctionBid.objects.filter(manor=manor).select_related(
        "slot__item_template", "slot__round", "slot__highest_bidder"
    )

    if not include_history:
        current_round = get_current_round()
        if current_round:
            queryset = queryset.filter(slot__round=current_round)
        else:
            return AuctionBid.objects.none()

    return queryset.order_by("-created_at")


def get_my_leading_bids(manor: Manor) -> List[AuctionSlot]:
    """获取我当前在中标范围内的拍卖位。"""
    current_round = get_current_round()
    if not current_round:
        return []

    my_active_bids = list(
        AuctionBid.objects.filter(
            manor=manor,
            status=AuctionBid.Status.ACTIVE,
            slot__round=current_round,
            slot__status=AuctionSlot.Status.ACTIVE,
        )
        .select_related("slot", "slot__item_template")
    )

    if not my_active_bids:
        return []

    # Batch fetch rankings to avoid N+1
    slot_ids = [bid.slot_id for bid in my_active_bids]

    # We need to sort by amount DESC, created_at ASC to determine rank
    # Fetching slot_id and manor_id is enough to determine position
    competitor_bids = (
        AuctionBid.objects.filter(
            slot_id__in=slot_ids,
            status=AuctionBid.Status.ACTIVE
        )
        .values_list("slot_id", "manor_id")
        .order_by("slot_id", "-amount", "created_at")
    )

    # Group by slot in memory
    rankings_map = {}
    for slot_id, bidder_id in competitor_bids:
        if slot_id not in rankings_map:
            rankings_map[slot_id] = []
        rankings_map[slot_id].append(bidder_id)

    result = []
    for bid in my_active_bids:
        slot = bid.slot
        rank_list = rankings_map.get(slot.id, [])

        # Check if I am in top N
        try:
            # list.index raises ValueError if not found
            # 1-based rank
            rank = rank_list.index(manor.id) + 1
            if rank <= slot.quantity:
                result.append(slot)
        except ValueError:
            continue

    return result


def get_my_safe_slots_count(manor: Manor) -> int:
    """获取我当前在中标范围内的拍卖位数量（维克里拍卖）。"""
    return len(get_my_leading_bids(manor))


def get_slot_bid_info(slot: AuctionSlot, manor: Manor = None) -> Dict:
    """获取拍卖位的出价信息（维克里拍卖，不含具体排名）。"""
    ranking = get_slot_ranking(slot)
    winner_count = slot.quantity
    bidder_count = len(ranking)
    cutoff_price = get_cutoff_price(slot, ranking=ranking)

    info = {
        "winner_count": winner_count,
        "bidder_count": bidder_count,
        "cutoff_price": cutoff_price,
        "is_full": bidder_count >= winner_count,
        "my_bid_amount": None,
        "is_safe": None,
    }

    if manor:
        my_bid = next((b for b in ranking if b.manor_id == manor.id), None)
        if my_bid:
            info["my_bid_amount"] = my_bid.amount
            info["is_safe"] = is_in_winning_range(slot, manor)

    return info


def get_slots_bid_info_batch(slots: List[AuctionSlot], manor: Manor = None) -> Dict[int, Dict]:
    """批量获取多个拍卖位的出价信息（优化 N+1 查询）。"""
    if not slots:
        return {}

    slot_ids = [slot.id for slot in slots]
    all_bids = list(
        AuctionBid.objects.filter(slot_id__in=slot_ids, status=AuctionBid.Status.ACTIVE)
        .order_by("slot_id", "-amount")
        .select_related("manor")
    )

    bids_by_slot: Dict[int, List[AuctionBid]] = {}
    for bid in all_bids:
        bids_by_slot.setdefault(bid.slot_id, []).append(bid)

    result: Dict[int, Dict] = {}
    for slot in slots:
        ranking = bids_by_slot.get(slot.id, [])
        winner_count = slot.quantity
        bidder_count = len(ranking)
        cutoff_price = ranking[winner_count - 1].amount if len(ranking) >= winner_count else slot.starting_price

        info = {
            "winner_count": winner_count,
            "bidder_count": bidder_count,
            "cutoff_price": cutoff_price,
            "is_full": bidder_count >= winner_count,
            "my_bid_amount": None,
            "is_safe": None,
        }

        if manor:
            my_bid = next((b for b in ranking if b.manor_id == manor.id), None)
            if my_bid:
                info["my_bid_amount"] = my_bid.amount
                my_rank = next((i + 1 for i, b in enumerate(ranking) if b.manor_id == manor.id), None)
                info["is_safe"] = my_rank is not None and my_rank <= winner_count

        result[slot.id] = info

    return result


def get_auction_stats(manor: Manor = None) -> Dict:
    """获取拍卖行统计信息（维克里拍卖）。"""
    current_round = get_current_round()
    stats = {
        "current_round": None,
        "time_remaining": 0,
        "total_slots": 0,
        "active_slots": 0,
        "my_leading_count": 0,
        "my_frozen_gold_bars": 0,
        "available_gold_bars": 0,
    }

    if current_round:
        stats["current_round"] = current_round.round_number
        stats["time_remaining"] = current_round.time_remaining
        stats["total_slots"] = current_round.slots.count()
        stats["active_slots"] = current_round.slots.filter(status=AuctionSlot.Status.ACTIVE).count()

    if manor:
        if current_round:
            stats["my_leading_count"] = get_my_safe_slots_count(manor)
        stats["my_frozen_gold_bars"] = get_frozen_gold_bars(manor)
        stats["available_gold_bars"] = get_available_gold_bars(manor)

    return stats
