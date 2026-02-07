"""Auction round creation and settlement logic."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Callable, Dict, Optional

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from gameplay.models import ItemTemplate, Manor
from gameplay.services.messages import create_message
from gameplay.services.notifications import notify_user
from trade.models import AuctionBid, AuctionRound, AuctionSlot, FrozenGoldBar

from trade.services.auction_config import get_auction_settings, get_enabled_auction_items

from .constants import (
    AUCTION_CREATE_LOCK_KEY,
    AUCTION_CREATE_LOCK_TIMEOUT,
    AUCTION_SETTLE_LOCK_KEY,
    AUCTION_SETTLE_LOCK_TIMEOUT,
    GOLD_BAR_ITEM_KEY,
)
from .bidding import get_slot_ranking
from .gold_bars import consume_frozen_gold_bars, unfreeze_gold_bars

logger = logging.getLogger(__name__)


def get_current_round() -> Optional[AuctionRound]:
    """获取当前进行中的拍卖轮次。"""
    return AuctionRound.objects.filter(status=AuctionRound.Status.ACTIVE).first()


def get_next_round_number() -> int:
    """获取下一轮次编号。"""
    last_round = AuctionRound.objects.order_by("-round_number").first()
    return (last_round.round_number + 1) if last_round else 1


def create_auction_round(
    *,
    get_settings_func: Callable[[], object] | None = None,
    get_enabled_items_func: Callable[[], list] | None = None,
) -> Optional[AuctionRound]:
    """创建新的拍卖轮次（若已有进行中则跳过）。

    Args:
        get_settings_func: Optional dependency injection for reading auction settings.
        get_enabled_items_func: Optional dependency injection for enabled auction items.
    """
    lock_value = str(uuid.uuid4())
    lock_acquired = cache.add(AUCTION_CREATE_LOCK_KEY, lock_value, timeout=AUCTION_CREATE_LOCK_TIMEOUT)
    if not lock_acquired:
        logger.info("拍卖轮次创建锁未获取，跳过本次创建")
        return None

    try:
        settings = (get_settings_func or get_auction_settings)()
        enabled_items = (get_enabled_items_func or get_enabled_auction_items)()

        if not enabled_items:
            logger.warning("没有启用的拍卖商品，跳过创建轮次")
            return None

        now = timezone.now()
        end_at = now + timedelta(days=settings.cycle_days)

        with transaction.atomic():
            if (
                AuctionRound.objects.select_for_update()
                .filter(status__in=[AuctionRound.Status.ACTIVE, AuctionRound.Status.SETTLING])
                .exists()
            ):
                logger.info("已有进行中或结算中的拍卖轮次，跳过创建")
                return None

            last_round = AuctionRound.objects.select_for_update().order_by("-round_number").first()
            round_number = (last_round.round_number + 1) if last_round else 1

            try:
                auction_round = AuctionRound.objects.create(
                    round_number=round_number,
                    status=AuctionRound.Status.ACTIVE,
                    start_at=now,
                    end_at=end_at,
                )
            except IntegrityError:
                logger.warning("创建拍卖轮次时发生编号冲突，跳过本次创建")
                return None

            item_keys = [item_config.item_key for item_config in enabled_items]
            templates_map = {t.key: t for t in ItemTemplate.objects.filter(key__in=item_keys)}

            slots_to_create = []
            for item_config in enabled_items:
                item_template = templates_map.get(item_config.item_key)
                if not item_template:
                    logger.warning(f"物品模板不存在: {item_config.item_key}，跳过")
                    continue

                for slot_index in range(item_config.slots):
                    slots_to_create.append(
                        AuctionSlot(
                            round=auction_round,
                            item_template=item_template,
                            quantity=item_config.quantity_per_slot,
                            starting_price=item_config.starting_price,
                            current_price=item_config.starting_price,
                            min_increment=item_config.min_increment,
                            status=AuctionSlot.Status.ACTIVE,
                            config_key=item_config.item_key,
                            slot_index=slot_index,
                        )
                    )

            if slots_to_create:
                AuctionSlot.objects.bulk_create(slots_to_create)

            logger.info(f"创建拍卖轮次 #{round_number}，共 {len(slots_to_create)} 个拍卖位")

        return auction_round
    finally:
        if cache.get(AUCTION_CREATE_LOCK_KEY) == lock_value:
            cache.delete(AUCTION_CREATE_LOCK_KEY)


def settle_auction_round(
    round_id: int = None,
    *,
    settle_slot_func: Callable[[AuctionSlot], Dict] | None = None,
) -> Dict:
    """结算拍卖轮次。

    Args:
        settle_slot_func: Optional dependency injection for settling a single slot.
            Defaults to internal `_settle_slot`.
    """
    stats = {"settled": 0, "sold": 0, "unsold": 0, "total_gold_bars": 0}

    lock_value = str(uuid.uuid4())
    lock_acquired = cache.add(AUCTION_SETTLE_LOCK_KEY, lock_value, timeout=AUCTION_SETTLE_LOCK_TIMEOUT)
    if not lock_acquired:
        logger.info("拍卖结算锁未获取，跳过本次结算")
        return stats

    try:
        with transaction.atomic():
            if round_id:
                auction_round = (
                    AuctionRound.objects.select_for_update()
                    .filter(id=round_id, status__in=[AuctionRound.Status.ACTIVE, AuctionRound.Status.SETTLING])
                    .first()
                )
            else:
                auction_round = (
                    AuctionRound.objects.select_for_update()
                    .filter(
                        status__in=[AuctionRound.Status.ACTIVE, AuctionRound.Status.SETTLING],
                        end_at__lte=timezone.now(),
                    )
                    .order_by("end_at", "id")
                    .first()
                )

            if not auction_round:
                logger.info("没有需要结算的拍卖轮次")
                return stats

            if auction_round.status != AuctionRound.Status.SETTLING:
                auction_round.status = AuctionRound.Status.SETTLING
                auction_round.save(update_fields=["status"])

        slots = (
            AuctionSlot.objects.filter(round=auction_round, status=AuctionSlot.Status.ACTIVE)
            .select_related("item_template", "highest_bidder")
        )

        failed_slots = []
        settle_one = settle_slot_func or _settle_slot
        for slot in slots:
            try:
                result = settle_one(slot)
                if result["sold"]:
                    stats["sold"] += 1
                    stats["total_gold_bars"] += result["price"]
                else:
                    stats["unsold"] += 1
            except Exception as exc:
                logger.exception(f"结算拍卖位 {slot.id} 时出错：{exc}")
                failed_slots.append({"slot_id": slot.id, "error": str(exc)})
                continue

        if failed_slots:
            logger.error(
                f"拍卖轮次 #{auction_round.round_number} 有 {len(failed_slots)} 个拍卖位结算失败",
                extra={"failed_slots": failed_slots},
            )
            stats["failed"] = len(failed_slots)
            stats["failed_details"] = failed_slots
            raise RuntimeError(f"拍卖轮次 #{auction_round.round_number} 结算失败：{len(failed_slots)} 个拍卖位异常")

        with transaction.atomic():
            locked_round = AuctionRound.objects.select_for_update().get(pk=auction_round.pk)
            locked_round.status = AuctionRound.Status.COMPLETED
            locked_round.settled_at = timezone.now()
            locked_round.save(update_fields=["status", "settled_at"])

        stats["settled"] = 1
        logger.info(
            f"拍卖轮次 #{auction_round.round_number} 结算完成，"
            f"售出 {stats['sold']} 件，流拍 {stats['unsold']} 件，"
            f"共收取 {stats['total_gold_bars']} 金条"
        )
        return stats
    finally:
        if cache.get(AUCTION_SETTLE_LOCK_KEY) == lock_value:
            cache.delete(AUCTION_SETTLE_LOCK_KEY)


def _settle_slot(slot: AuctionSlot) -> Dict:
    """结算单个拍卖位（维克里拍卖）。"""
    result = {"sold": False, "price": 0, "winner_count": 0}

    with transaction.atomic():
        slot = AuctionSlot.objects.select_for_update().get(pk=slot.pk)

        ranking = get_slot_ranking(slot)
        winner_count = slot.quantity

        if not ranking:
            slot.status = AuctionSlot.Status.UNSOLD
            slot.save(update_fields=["status"])
            return result

        actual_winners = ranking[:winner_count]
        actual_winner_count = len(actual_winners)
        settlement_price = actual_winners[-1].amount

        for winning_bid in actual_winners:
            winner = winning_bid.manor

            frozen_amount = winning_bid.frozen_gold_bars
            refund_amount = frozen_amount - settlement_price

            if refund_amount > 0:
                _partial_consume_frozen_gold_bars(winning_bid, winner, settlement_price, refund_amount)
            else:
                try:
                    if winning_bid.frozen_record:
                        consume_frozen_gold_bars(winning_bid.frozen_record, winner)
                except FrozenGoldBar.DoesNotExist:
                    pass

            winning_bid.status = AuctionBid.Status.WON
            winning_bid.save(update_fields=["status"])

            _send_winning_notification_vickrey(slot, winner, settlement_price, actual_winner_count)

            result["price"] += settlement_price

        result["sold"] = True
        result["winner_count"] = actual_winner_count

        # Mark losers and update their bid status to keep data consistent.
        for losing_bid in ranking[winner_count:]:
            try:
                if losing_bid.frozen_record and losing_bid.frozen_record.is_frozen:
                    unfreeze_gold_bars(losing_bid.frozen_record)
            except FrozenGoldBar.DoesNotExist:
                pass

            losing_bid.status = AuctionBid.Status.REFUNDED
            losing_bid.refunded_at = timezone.now()
            losing_bid.save(update_fields=["status", "refunded_at"])

        slot.status = AuctionSlot.Status.SOLD
        slot.save(update_fields=["status"])

    return result


def _partial_consume_frozen_gold_bars(bid: AuctionBid, manor: Manor, consume_amount: int, refund_amount: int) -> None:
    """部分消耗冻结金条（用于维克里拍卖，出价高于结算价的情况）。"""
    from gameplay.services.inventory import consume_inventory_item_for_manor_locked

    try:
        frozen_record = bid.frozen_record
    except FrozenGoldBar.DoesNotExist:
        return

    if not frozen_record or not frozen_record.is_frozen:
        return

    with transaction.atomic():
        locked_record = FrozenGoldBar.objects.select_for_update().filter(pk=frozen_record.pk, is_frozen=True).first()
        if not locked_record:
            return

        consume_inventory_item_for_manor_locked(manor, GOLD_BAR_ITEM_KEY, consume_amount)

        locked_record.is_frozen = False
        locked_record.unfrozen_at = timezone.now()
        locked_record.save(update_fields=["is_frozen", "unfrozen_at"])

    logger.info(
        f"维克里拍卖结算: 庄园 {manor.id} 实际扣除 {consume_amount} 金条，"
        f"退还 {refund_amount} 金条"
    )


def _send_winning_notification_vickrey(
    slot: AuctionSlot, winner: Manor, settlement_price: int, total_winners: int
) -> None:
    """发送中标通知并发放物品（维克里拍卖，每人1个）。"""
    create_message(
        manor=winner,
        kind="reward",
        title="【拍卖行】恭喜您成功拍得物品",
        body=(
            f"恭喜！您成功拍得 {slot.item_template.name} x1！\n\n"
            f"拍卖详情：\n"
            f"- 物品：{slot.item_template.name}\n"
            f"- 数量：1\n"
            f"- 结算价：{settlement_price} 金条（统一结算价）\n"
            f"- 中标人数：{total_winners}\n"
            f"- 拍卖轮次：第{slot.round.round_number}轮\n\n"
            f"物品已通过附件发放，请查收。"
        ),
        attachments={
            "items": {slot.item_template.key: 1},
        },
    )

    notify_user(
        winner.user_id,
        {
            "kind": "auction_won",
            "title": "【拍卖行】恭喜您成功拍得物品",
            "item_name": slot.item_template.name,
            "item_key": slot.item_template.key,
            "quantity": 1,
            "price": settlement_price,
            "total_winners": total_winners,
        },
        log_context="auction won notification",
    )
