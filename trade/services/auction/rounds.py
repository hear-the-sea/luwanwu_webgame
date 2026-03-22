"""Auction round creation and settlement logic."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.exceptions import MessageError
from core.utils.infrastructure import (
    CACHE_INFRASTRUCTURE_EXCEPTIONS,
    DATABASE_INFRASTRUCTURE_EXCEPTIONS,
    NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
    InfrastructureExceptions,
    combine_infrastructure_exceptions,
)
from gameplay.models import ItemTemplate, Manor
from gameplay.services.inventory.core import add_item_to_inventory_locked, consume_inventory_item_for_manor_locked
from gameplay.services.utils.messages import create_message
from gameplay.services.utils.notifications import notify_user
from trade.models import AuctionBid, AuctionRound, AuctionSlot, FrozenGoldBar
from trade.services.auction.bidding import get_slot_ranking
from trade.services.auction.constants import (
    AUCTION_CREATE_LOCK_KEY,
    AUCTION_CREATE_LOCK_TIMEOUT,
    AUCTION_SETTLE_LOCK_KEY,
    AUCTION_SETTLE_LOCK_TIMEOUT,
    GOLD_BAR_ITEM_KEY,
)
from trade.services.auction.gold_bars import consume_frozen_gold_bars, try_get_frozen_record, unfreeze_gold_bars
from trade.services.auction_config import (
    AuctionItemConfig,
    AuctionSettings,
    get_auction_settings,
    get_enabled_auction_items,
)
from trade.services.cache_resilience import best_effort_cache_add, best_effort_cache_delete, best_effort_cache_get

logger = logging.getLogger(__name__)


AUCTION_INFRASTRUCTURE_EXCEPTIONS: InfrastructureExceptions = CACHE_INFRASTRUCTURE_EXCEPTIONS
AUCTION_CACHE_COMPONENT = "auction_cache"
AUCTION_MESSAGE_DELIVERY_EXCEPTIONS: InfrastructureExceptions = combine_infrastructure_exceptions(
    MessageError,
    infrastructure_exceptions=DATABASE_INFRASTRUCTURE_EXCEPTIONS,
)


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_cache_add(key: str, value: Any, timeout: int) -> bool:
    return best_effort_cache_add(
        cache,
        key,
        value,
        timeout,
        logger=logger,
        component=AUCTION_CACHE_COMPONENT,
        infrastructure_exceptions=AUCTION_INFRASTRUCTURE_EXCEPTIONS,
    )


def _safe_cache_get(key: str, default: Any = None) -> Any:
    return best_effort_cache_get(
        cache,
        key,
        default,
        logger=logger,
        component=AUCTION_CACHE_COMPONENT,
        infrastructure_exceptions=AUCTION_INFRASTRUCTURE_EXCEPTIONS,
    )


def _safe_cache_delete(key: str) -> None:
    best_effort_cache_delete(
        cache,
        key,
        logger=logger,
        component=AUCTION_CACHE_COMPONENT,
        infrastructure_exceptions=AUCTION_INFRASTRUCTURE_EXCEPTIONS,
    )


def _safe_notify_user(user_id: int, payload: dict, *, log_context: str) -> None:
    try:
        notify_user(user_id, payload, log_context=log_context)
    except NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.warning(
            "auction winning notify_user failed: user_id=%s error=%s",
            user_id,
            exc,
            exc_info=True,
        )


def get_current_round() -> Optional[AuctionRound]:
    """获取当前进行中的拍卖轮次。"""
    return AuctionRound.objects.filter(status=AuctionRound.Status.ACTIVE).first()


def get_next_round_number() -> int:
    """获取下一轮次编号。"""
    last_round = AuctionRound.objects.order_by("-round_number").first()
    return (last_round.round_number + 1) if last_round else 1


def create_auction_round(
    *,
    get_settings_func: Callable[[], AuctionSettings] | None = None,
    get_enabled_items_func: Callable[[], List[AuctionItemConfig]] | None = None,
) -> Optional[AuctionRound]:
    """创建新的拍卖轮次（若已有进行中则跳过）。

    Args:
        get_settings_func: Optional dependency injection for reading auction settings.
        get_enabled_items_func: Optional dependency injection for enabled auction items.
    """
    lock_value = str(uuid.uuid4())
    lock_acquired = _safe_cache_add(AUCTION_CREATE_LOCK_KEY, lock_value, timeout=AUCTION_CREATE_LOCK_TIMEOUT)
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

            item_keys = [item_config.item_key for item_config in enabled_items]
            from core.utils.template_loader import load_templates_by_key

            templates_map = load_templates_by_key(ItemTemplate, keys=item_keys)

            slots_to_create = []
            for item_config in enabled_items:
                item_template = templates_map.get(item_config.item_key)
                if not item_template:
                    logger.warning("物品模板不存在: %s，跳过", item_config.item_key)
                    continue

                for slot_index in range(item_config.slots):
                    slots_to_create.append(
                        {
                            "item_template": item_template,
                            "quantity": item_config.quantity_per_slot,
                            "starting_price": item_config.starting_price,
                            "current_price": item_config.starting_price,
                            "min_increment": item_config.min_increment,
                            "status": AuctionSlot.Status.ACTIVE,
                            "config_key": item_config.item_key,
                            "slot_index": slot_index,
                        }
                    )

            if not slots_to_create:
                logger.warning("本轮拍卖没有可创建的拍卖位，跳过创建轮次")
                return None

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

            AuctionSlot.objects.bulk_create(
                [AuctionSlot(round=auction_round, **slot_data) for slot_data in slots_to_create]
            )

            logger.info("创建拍卖轮次 #%d，共 %d 个拍卖位", round_number, len(slots_to_create))

        return auction_round
    finally:
        if _safe_cache_get(AUCTION_CREATE_LOCK_KEY) == lock_value:
            _safe_cache_delete(AUCTION_CREATE_LOCK_KEY)


def settle_auction_round(
    round_id: int = None,
    *,
    settle_slot_func: Callable[[AuctionSlot], Dict] | None = None,
) -> Dict[str, Any]:
    """结算拍卖轮次。

    Args:
        settle_slot_func: Optional dependency injection for settling a single slot.
            Defaults to internal `_settle_slot`.
    """
    stats: Dict[str, Any] = {"settled": 0, "sold": 0, "unsold": 0, "total_gold_bars": 0}

    lock_value = str(uuid.uuid4())
    lock_acquired = _safe_cache_add(AUCTION_SETTLE_LOCK_KEY, lock_value, timeout=AUCTION_SETTLE_LOCK_TIMEOUT)
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

        slots = AuctionSlot.objects.filter(round=auction_round, status=AuctionSlot.Status.ACTIVE).select_related(
            "item_template", "highest_bidder"
        )

        failed_slots = []
        settle_one = settle_slot_func or _settle_slot

        for slot in slots:
            try:
                result = settle_one(slot)
                if not isinstance(result, dict):
                    raise AssertionError(f"invalid settle slot result for slot={slot.id}: {result!r}")

                if result.get("skipped"):
                    continue

                if result.get("sold"):
                    stats["sold"] += 1
                    stats["total_gold_bars"] += max(0, _safe_int(result.get("price", 0), 0))
                else:
                    stats["unsold"] += 1
            except AssertionError:
                raise
            except DATABASE_INFRASTRUCTURE_EXCEPTIONS as exc:
                logger.exception("结算拍卖位 %s 时出错: %s", slot.id, exc)
                if _mark_slot_unsold_after_failure(slot):
                    stats["unsold"] += 1
                    failed_slots.append({"slot_id": slot.id, "error": str(exc), "recovered": True})
                    continue
                failed_slots.append({"slot_id": slot.id, "error": str(exc), "recovered": False})
                continue

        unrecovered_failures = [entry for entry in failed_slots if not entry.get("recovered")]
        if unrecovered_failures:
            with transaction.atomic():
                locked_round = AuctionRound.objects.select_for_update().get(pk=auction_round.pk)
                locked_round.status = AuctionRound.Status.ACTIVE
                locked_round.save(update_fields=["status"])
            logger.error(
                f"拍卖轮次 #{auction_round.round_number} 有 {len(unrecovered_failures)} 个拍卖位结算失败",
                extra={"failed_slots": unrecovered_failures},
            )
            stats["failed"] = len(unrecovered_failures)
            stats["failed_details"] = unrecovered_failures
            raise RuntimeError(
                f"拍卖轮次 #{auction_round.round_number} 结算失败：{len(unrecovered_failures)} 个拍卖位异常"
            )

        recovered_failures = [entry for entry in failed_slots if entry.get("recovered")]
        if recovered_failures:
            stats["recovered_failures"] = len(recovered_failures)
            stats["recovered_failure_details"] = recovered_failures

        with transaction.atomic():
            locked_round = AuctionRound.objects.select_for_update().get(pk=auction_round.pk)

            # 并发保护：若仍有 ACTIVE 拍卖位，说明可能有其他结算进程在处理，不提前完结轮次。
            if AuctionSlot.objects.filter(round=locked_round, status=AuctionSlot.Status.ACTIVE).exists():
                logger.info("拍卖轮次 #%s 仍有未完成拍卖位，保持 SETTLING 状态", locked_round.round_number)
                return stats

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
        if _safe_cache_get(AUCTION_SETTLE_LOCK_KEY) == lock_value:
            _safe_cache_delete(AUCTION_SETTLE_LOCK_KEY)


def _refund_losing_bids(losing_bids: list[AuctionBid]) -> None:
    for losing_bid in losing_bids:
        try:
            if losing_bid.frozen_record and losing_bid.frozen_record.is_frozen:
                unfreeze_gold_bars(losing_bid.frozen_record)
        except FrozenGoldBar.DoesNotExist:
            pass

        losing_bid.status = AuctionBid.Status.REFUNDED
        losing_bid.refunded_at = timezone.now()
        losing_bid.save(update_fields=["status", "refunded_at"])


def _mark_slot_unsold_after_failure(slot: AuctionSlot) -> bool:
    try:
        with transaction.atomic():
            locked_slot = AuctionSlot.objects.select_for_update().get(pk=slot.pk)
            if locked_slot.status != AuctionSlot.Status.ACTIVE:
                return True

            active_bids = list(
                AuctionBid.objects.select_for_update().filter(slot=locked_slot, status=AuctionBid.Status.ACTIVE)
            )
            if active_bids:
                _refund_losing_bids(active_bids)

            locked_slot.status = AuctionSlot.Status.UNSOLD
            locked_slot.save(update_fields=["status"])
            return True
    except DATABASE_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.exception("failed to force slot %s unsold after settlement error: %s", slot.id, exc)
        return False


def _consume_winning_bid_frozen_gold_bars(winning_bid: AuctionBid, winner: Manor, settlement_price: int) -> None:
    frozen_record = try_get_frozen_record(winning_bid)
    if not frozen_record:
        raise RuntimeError(f"winning bid missing frozen record: bid_id={winning_bid.id}")
    if not frozen_record.is_frozen:
        raise RuntimeError(f"winning bid frozen record already unfrozen: bid_id={winning_bid.id}")

    frozen_amount = _safe_int(getattr(frozen_record, "amount", 0), 0)
    if frozen_amount <= 0:
        raise RuntimeError(f"winning bid frozen amount invalid: bid_id={winning_bid.id} amount={frozen_amount}")
    if settlement_price <= 0:
        raise RuntimeError(
            f"winning bid settlement price invalid: bid_id={winning_bid.id} settlement_price={settlement_price}"
        )
    if frozen_amount < settlement_price:
        raise RuntimeError(
            f"winning bid frozen amount insufficient: bid_id={winning_bid.id} amount={frozen_amount} price={settlement_price}"
        )

    refund_amount = frozen_amount - settlement_price
    if refund_amount > 0:
        _partial_consume_frozen_gold_bars(winning_bid, winner, settlement_price, refund_amount)
    else:
        consume_frozen_gold_bars(frozen_record, winner)


def _settle_slot(slot: AuctionSlot) -> Dict:
    """结算单个拍卖位（维克里拍卖）。"""
    result = {"sold": False, "price": 0, "winner_count": 0}

    with transaction.atomic():
        slot = AuctionSlot.objects.select_for_update().get(pk=slot.pk)

        if slot.status != AuctionSlot.Status.ACTIVE:
            return {**result, "skipped": True}

        ranking = get_slot_ranking(slot)
        winner_count = _safe_int(getattr(slot, "quantity", 0), 0)

        if not ranking:
            slot.status = AuctionSlot.Status.UNSOLD
            slot.save(update_fields=["status"])
            return result

        if winner_count <= 0:
            logger.error("拍卖位配置异常: slot_id=%s quantity=%s", slot.id, slot.quantity)
            _refund_losing_bids(ranking)
            slot.status = AuctionSlot.Status.UNSOLD
            slot.save(update_fields=["status"])
            return result

        actual_winners = ranking[:winner_count]
        actual_winner_count = len(actual_winners)
        settlement_price = actual_winners[-1].amount

        for winning_bid in actual_winners:
            winner = winning_bid.manor

            _consume_winning_bid_frozen_gold_bars(winning_bid, winner, settlement_price)

            winning_bid.status = AuctionBid.Status.WON
            winning_bid.save(update_fields=["status"])

            def _notify_winner(
                slot=slot,
                winner=winner,
                settlement_price=settlement_price,
                total_winners=actual_winner_count,
            ) -> None:
                _send_winning_notification_vickrey(slot, winner, settlement_price, total_winners)

            transaction.on_commit(_notify_winner)

            result["price"] += settlement_price

        result["sold"] = True
        result["winner_count"] = actual_winner_count

        # Mark losers and update their bid status to keep data consistent.
        _refund_losing_bids(ranking[winner_count:])

        slot.status = AuctionSlot.Status.SOLD
        slot.save(update_fields=["status"])

    return result


def _partial_consume_frozen_gold_bars(bid: AuctionBid, manor: Manor, consume_amount: int, refund_amount: int) -> None:
    """部分消耗冻结金条（用于维克里拍卖，出价高于结算价的情况）。"""
    frozen_record = try_get_frozen_record(bid)
    if not frozen_record:
        raise RuntimeError(f"partial consume missing frozen record: bid_id={bid.id}")
    if not frozen_record.is_frozen:
        raise RuntimeError(f"partial consume frozen record already unfrozen: bid_id={bid.id}")

    with transaction.atomic():
        locked_record = FrozenGoldBar.objects.select_for_update().filter(pk=frozen_record.pk, is_frozen=True).first()
        if not locked_record:
            raise RuntimeError(f"partial consume lock failed for frozen record: bid_id={bid.id}")

        locked_amount = _safe_int(getattr(locked_record, "amount", 0), 0)
        if locked_amount < consume_amount:
            raise RuntimeError(
                f"partial consume amount exceeds frozen amount: bid_id={bid.id} consume={consume_amount} amount={locked_amount}"
            )

        consume_inventory_item_for_manor_locked(manor, GOLD_BAR_ITEM_KEY, consume_amount)

        locked_record.is_frozen = False
        locked_record.unfrozen_at = timezone.now()
        locked_record.save(update_fields=["is_frozen", "unfrozen_at"])

    logger.info(f"维克里拍卖结算: 庄园 {manor.id} 实际扣除 {consume_amount} 金条，" f"退还 {refund_amount} 金条")


def _send_winning_notification_vickrey(
    slot: AuctionSlot, winner: Manor, settlement_price: int, total_winners: int
) -> None:
    """发送中标通知并发放物品（维克里拍卖，每人1个）。"""
    delivery_via_message = True
    try:
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
    except AUCTION_MESSAGE_DELIVERY_EXCEPTIONS as exc:
        delivery_via_message = False
        logger.exception(
            "auction winning message create failed, fallback to direct inventory grant: slot_id=%s manor_id=%s error=%s",
            slot.id,
            winner.id,
            exc,
        )
        _grant_auction_item_directly(winner, slot.item_template, quantity=1)

    _safe_notify_user(
        winner.user_id,
        {
            "kind": "auction_won",
            "title": "【拍卖行】恭喜您成功拍得物品",
            "item_name": slot.item_template.name,
            "item_key": slot.item_template.key,
            "quantity": 1,
            "price": settlement_price,
            "total_winners": total_winners,
            "delivery": "message_attachment" if delivery_via_message else "direct_inventory",
        },
        log_context="auction won notification",
    )


def _grant_auction_item_directly(manor: Manor, item_template: ItemTemplate, quantity: int) -> None:
    """Fallback path when reward message creation fails."""
    quantity = _safe_int(quantity, 0)
    if quantity <= 0:
        return

    with transaction.atomic():
        add_item_to_inventory_locked(manor, item_template.key, quantity)
