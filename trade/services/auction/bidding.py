"""Bidding logic (Vickrey auction) for auction service."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from gameplay.models import Manor
from gameplay.services.messages import create_message
from gameplay.services.notifications import notify_user
from trade.models import AuctionBid, AuctionRound, AuctionSlot, FrozenGoldBar

from .gold_bars import freeze_gold_bars, unfreeze_gold_bars

logger = logging.getLogger(__name__)


def get_slot_ranking(slot: AuctionSlot) -> List[AuctionBid]:
    """获取拍卖位的出价排名（按金额从高到低）"""
    return list(
        AuctionBid.objects.filter(
            slot=slot,
            status=AuctionBid.Status.ACTIVE,
        )
        .select_related("manor")
        .order_by("-amount", "created_at")  # 金额相同时，先出价者排前面
    )


def get_cutoff_price(slot: AuctionSlot, ranking: Optional[List[AuctionBid]] = None) -> int:
    """获取当前最低中标价（第N名的出价）。"""
    if ranking is None:
        ranking = get_slot_ranking(slot)
    winner_count = slot.quantity  # 中标名额数

    if len(ranking) >= winner_count:
        return ranking[winner_count - 1].amount
    if ranking:
        return ranking[-1].amount
    return slot.starting_price


def get_my_rank(slot: AuctionSlot, manor: Manor) -> Optional[int]:
    """获取我在某拍卖位的当前排名（1-based）。"""
    ranking = get_slot_ranking(slot)
    for i, bid in enumerate(ranking, start=1):
        if bid.manor_id == manor.id:
            return i
    return None


def is_in_winning_range(slot: AuctionSlot, manor: Manor) -> bool:
    """判断某庄园是否在中标范围内（前N名）。"""
    rank = get_my_rank(slot, manor)
    if rank is None:
        return False
    return rank <= slot.quantity


def validate_bid_amount(
    slot: AuctionSlot,
    amount: int,
    manor: Manor = None,
    ranking: Optional[List[AuctionBid]] = None,
    current_bid: Optional[AuctionBid] = None,
) -> None:
    """验证出价金额是否合法。"""
    # When there are no active bids, treat it as the first bid regardless of
    # `slot.bid_count` (which is a historical counter).
    if ranking is None:
        ranking = get_slot_ranking(slot)
    if not ranking and not current_bid:
        min_bid = slot.starting_price
        if amount < min_bid:
            raise ValueError(f"出价金额不得低于起拍价 {min_bid} 金条")
        return

    # 如果已有出价，检查是否为加价
    if current_bid:
        if amount <= current_bid.amount:
            raise ValueError(f"加价金额必须高于您之前的出价 {current_bid.amount} 金条")
        # 检查最小加价幅度
        if amount < current_bid.amount + slot.min_increment:
            raise ValueError(f"加价幅度至少为 {slot.min_increment} 金条")
        return

    if manor:
        my_bid = next((bid for bid in ranking if bid.manor_id == manor.id), None)
        if my_bid is not None:
            # 已有出价，需要比自己之前的出价高
            if amount <= my_bid.amount:
                raise ValueError(f"加价金额必须高于您之前的出价 {my_bid.amount} 金条")
            # 检查最小加价幅度
            if amount < my_bid.amount + slot.min_increment:
                raise ValueError(f"加价幅度至少为 {slot.min_increment} 金条")
            return

    # 新出价者，需要高于当前最低中标价才有意义
    cutoff = get_cutoff_price(slot, ranking=ranking)
    winner_count = slot.quantity

    if len(ranking) >= winner_count and amount <= cutoff:
        raise ValueError(f"出价金额需要高于当前最低中标价 {cutoff} 金条才能进入前 {winner_count} 名")


def place_bid(
    manor: Manor,
    slot_id: int,
    amount: int,
    *,
    notify_outbid_func=None,
) -> Tuple[AuctionBid, bool]:
    """玩家出价（维克里拍卖）。

    Args:
        notify_outbid_func: Optional callback for outbid notifications.
            Defaults to internal `_notify_outbid_vickrey`.
    """
    outbid_player = None  # 被挤出前N名的玩家

    with transaction.atomic():
        slot = (
            AuctionSlot.objects.select_for_update()
            .select_related("round", "item_template")
            .filter(id=slot_id)
            .first()
        )

        if not slot:
            raise ValueError("拍卖位不存在")

        # 验证拍卖状态
        if slot.status != AuctionSlot.Status.ACTIVE:
            raise ValueError("该拍卖位已结束")

        if slot.round.status != AuctionRound.Status.ACTIVE:
            raise ValueError("该拍卖轮次已结束")

        if slot.round.end_at <= timezone.now():
            raise ValueError("拍卖时间已结束")

        previous_bid = (
            AuctionBid.objects.select_for_update()
            .filter(
                slot=slot,
                manor=manor,
                status=AuctionBid.Status.ACTIVE,
            )
            .first()
        )

        # 安全修复：统一在事务开始时获取一次排名，避免 TOCTOU 问题和变量未定义
        ranking_before = get_slot_ranking(slot)

        # 验证出价金额
        if previous_bid:
            validate_bid_amount(slot, amount, current_bid=previous_bid)
        else:
            validate_bid_amount(slot, amount, ranking=ranking_before)

        # 如果有之前的出价，先解冻旧金条并标记旧出价（事务内，避免并发占用）
        if previous_bid:
            try:
                if previous_bid.frozen_record:
                    unfreeze_gold_bars(previous_bid.frozen_record)
            except FrozenGoldBar.DoesNotExist:
                pass
            # 标记为被自己新出价替代
            previous_bid.status = AuctionBid.Status.OUTBID
            previous_bid.save(update_fields=["status"])

        is_first_bid = previous_bid is None

        winner_count = slot.quantity

        player_to_kick = None
        if len(ranking_before) >= winner_count:
            player_to_kick = ranking_before[winner_count - 1]

        new_bid = AuctionBid.objects.create(
            slot=slot,
            manor=manor,
            amount=amount,
            status=AuctionBid.Status.ACTIVE,
        )

        freeze_gold_bars(manor, amount, new_bid)

        slot.bid_count += 1

        ranking_after = get_slot_ranking(slot)

        if player_to_kick and player_to_kick.manor_id != manor.id:
            still_in = False
            for i, bid in enumerate(ranking_after):
                if i >= winner_count:
                    break
                if bid.id == player_to_kick.id:
                    still_in = True
                    break

            if not still_in:
                outbid_player = player_to_kick.manor
                player_to_kick.status = AuctionBid.Status.OUTBID
                player_to_kick.save(update_fields=["status"])
                try:
                    if player_to_kick.frozen_record:
                        unfreeze_gold_bars(player_to_kick.frozen_record)
                except FrozenGoldBar.DoesNotExist:
                    pass

        if len(ranking_after) >= winner_count:
            slot.current_price = ranking_after[winner_count - 1].amount
        elif ranking_after:
            slot.current_price = ranking_after[-1].amount
        else:
            slot.current_price = slot.starting_price

        if ranking_after:
            slot.highest_bidder = ranking_after[0].manor
        else:
            slot.highest_bidder = manor

        slot.save(update_fields=["current_price", "highest_bidder", "bid_count"])

    if outbid_player:
        (notify_outbid_func or _notify_outbid_vickrey)(outbid_player, slot, amount, manor, winner_count)

    return new_bid, is_first_bid


def _notify_outbid_vickrey(manor: Manor, slot: AuctionSlot, new_price: int, new_bidder: Manor, winner_count: int) -> None:
    """通知玩家被挤出中标范围（维克里拍卖）。"""
    create_message(
        manor=manor,
        kind="system",
        title="【拍卖行】您已被挤出中标范围",
        body=(
            f"在 {slot.item_template.name} 的拍卖中，您已被挤出前 {winner_count} 名！\n\n"
            f"当前最低中标价：{new_price} 金条\n\n"
            f"您冻结的金条已自动退还，如需继续竞拍请尽快加价。"
        ),
    )

    notify_user(
        manor.user_id,
        {
            "kind": "auction_outbid",
            "title": "【拍卖行】您已被挤出中标范围",
            "item_name": slot.item_template.name,
            "item_key": slot.item_template.key,
            "new_price": new_price,
            "winner_count": winner_count,
        },
        log_context="auction outbid notification",
    )
