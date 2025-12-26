"""
拍卖行核心服务

处理拍卖轮次管理、出价、金条冻结/解冻、结算等核心逻辑。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from gameplay.models import ItemTemplate, Manor
from gameplay.services.inventory import add_item_to_inventory, get_item_quantity
from gameplay.services.messages import create_message
from trade.models import AuctionBid, AuctionRound, AuctionSlot, FrozenGoldBar

from .auction_config import get_auction_settings, get_enabled_auction_items

logger = logging.getLogger(__name__)

GOLD_BAR_ITEM_KEY = "gold_bar"


# ============ 金条管理 ============


def get_total_gold_bars(manor: Manor) -> int:
    """获取庄园持有的总金条数量"""
    return get_item_quantity(manor, GOLD_BAR_ITEM_KEY)


def get_frozen_gold_bars(manor: Manor) -> int:
    """获取庄园被冻结的金条数量"""
    result = FrozenGoldBar.objects.filter(manor=manor, is_frozen=True).aggregate(
        total=Sum("amount")
    )
    return result["total"] or 0


def get_available_gold_bars(manor: Manor) -> int:
    """获取庄园可用的金条数量（总数 - 冻结数）"""
    total = get_total_gold_bars(manor)
    frozen = get_frozen_gold_bars(manor)
    return max(0, total - frozen)


def freeze_gold_bars(manor: Manor, amount: int, bid: AuctionBid) -> FrozenGoldBar:
    """
    冻结金条用于拍卖出价

    Args:
        manor: 庄园
        amount: 冻结数量
        bid: 关联的出价记录

    Returns:
        FrozenGoldBar: 冻结记录

    Raises:
        ValueError: 可用金条不足时抛出
    """
    available = get_available_gold_bars(manor)
    if available < amount:
        raise ValueError(f"可用金条不足，当前可用 {available} 根，需要 {amount} 根")

    frozen_record = FrozenGoldBar.objects.create(
        manor=manor,
        amount=amount,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    # 更新出价记录的冻结金条数
    bid.frozen_gold_bars = amount
    bid.save(update_fields=["frozen_gold_bars"])

    return frozen_record


def unfreeze_gold_bars(frozen_record: FrozenGoldBar) -> None:
    """
    解冻金条（落选时调用）

    Args:
        frozen_record: 冻结记录
    """
    if not frozen_record.is_frozen:
        return

    frozen_record.is_frozen = False
    frozen_record.unfrozen_at = timezone.now()
    frozen_record.save(update_fields=["is_frozen", "unfrozen_at"])

    # 更新关联出价记录的状态
    if frozen_record.auction_bid:
        bid = frozen_record.auction_bid
        bid.status = AuctionBid.Status.REFUNDED
        bid.refunded_at = timezone.now()
        bid.save(update_fields=["status", "refunded_at"])


def consume_frozen_gold_bars(frozen_record: FrozenGoldBar, manor: Manor) -> None:
    """
    消耗冻结的金条（中标时调用）

    Args:
        frozen_record: 冻结记录
        manor: 庄园
    """
    from gameplay.services.inventory import consume_inventory_item

    if not frozen_record.is_frozen:
        return

    # 实际扣除金条
    consume_inventory_item(manor, GOLD_BAR_ITEM_KEY, frozen_record.amount)

    # 更新冻结记录
    frozen_record.is_frozen = False
    frozen_record.unfrozen_at = timezone.now()
    frozen_record.save(update_fields=["is_frozen", "unfrozen_at"])

    # 更新关联出价记录的状态
    if frozen_record.auction_bid:
        bid = frozen_record.auction_bid
        bid.status = AuctionBid.Status.WON
        bid.save(update_fields=["status"])


# ============ 轮次管理 ============


def get_current_round() -> Optional[AuctionRound]:
    """获取当前进行中的拍卖轮次"""
    return AuctionRound.objects.filter(status=AuctionRound.Status.ACTIVE).first()


def get_next_round_number() -> int:
    """获取下一轮次编号"""
    last_round = AuctionRound.objects.order_by("-round_number").first()
    return (last_round.round_number + 1) if last_round else 1


def create_auction_round() -> Optional[AuctionRound]:
    """
    创建新的拍卖轮次

    如果已有进行中的轮次则不创建。

    Returns:
        AuctionRound: 新创建的轮次，如果已存在进行中轮次则返回 None
    """
    # 检查是否已有进行中的轮次
    if get_current_round():
        logger.info("已有进行中的拍卖轮次，跳过创建")
        return None

    settings = get_auction_settings()
    enabled_items = get_enabled_auction_items()

    if not enabled_items:
        logger.warning("没有启用的拍卖商品，跳过创建轮次")
        return None

    round_number = get_next_round_number()
    now = timezone.now()
    end_at = now + timedelta(days=settings.cycle_days)

    with transaction.atomic():
        # 创建轮次
        auction_round = AuctionRound.objects.create(
            round_number=round_number,
            status=AuctionRound.Status.ACTIVE,
            start_at=now,
            end_at=end_at,
        )

        # 预先获取所有物品模板
        item_keys = [item_config.item_key for item_config in enabled_items]
        templates_map = {
            t.key: t for t in ItemTemplate.objects.filter(key__in=item_keys)
        }

        # 批量创建拍卖位
        slots_to_create = []
        for item_config in enabled_items:
            item_template = templates_map.get(item_config.item_key)
            if not item_template:
                logger.warning(f"物品模板不存在: {item_config.item_key}，跳过")
                continue

            # 创建多个拍卖位（分单拍卖）
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

        logger.info(
            f"创建拍卖轮次 #{round_number}，共 {len(slots_to_create)} 个拍卖位"
        )

    return auction_round


# ============ 出价逻辑（维克里拍卖） ============
#
# 维克里拍卖规则：
# - 一个拍卖位有 N 个中标名额（slot.quantity）
# - 前 N 名出价者各获得 1 个物品
# - 所有中标者支付统一价格（第 N 名的出价，即最低中标价）
# - 只有被挤出前 N 名时才退还金条


def get_slot_ranking(slot: AuctionSlot) -> List[AuctionBid]:
    """
    获取拍卖位的出价排名（按金额从高到低）

    Args:
        slot: 拍卖位

    Returns:
        按金额排序的有效出价列表
    """
    return list(
        AuctionBid.objects.filter(
            slot=slot,
            status=AuctionBid.Status.ACTIVE,
        )
        .select_related("manor")
        .order_by("-amount", "created_at")  # 金额相同时，先出价者排前面
    )


def get_cutoff_price(slot: AuctionSlot) -> int:
    """
    获取当前最低中标价（第N名的出价）

    Args:
        slot: 拍卖位

    Returns:
        最低中标价，如果出价人数不足N则返回起拍价
    """
    ranking = get_slot_ranking(slot)
    winner_count = slot.quantity  # 中标名额数

    if len(ranking) >= winner_count:
        return ranking[winner_count - 1].amount
    elif ranking:
        return ranking[-1].amount
    else:
        return slot.starting_price


def get_my_rank(slot: AuctionSlot, manor: Manor) -> Optional[int]:
    """
    获取我在某拍卖位的当前排名

    Args:
        slot: 拍卖位
        manor: 庄园

    Returns:
        排名（1-based），如果没有出价返回None
    """
    ranking = get_slot_ranking(slot)
    for i, bid in enumerate(ranking, start=1):
        if bid.manor_id == manor.id:
            return i
    return None


def is_in_winning_range(slot: AuctionSlot, manor: Manor) -> bool:
    """
    判断某庄园是否在中标范围内（前N名）

    Args:
        slot: 拍卖位
        manor: 庄园

    Returns:
        是否在前N名中
    """
    rank = get_my_rank(slot, manor)
    if rank is None:
        return False
    return rank <= slot.quantity


def validate_bid_amount(slot: AuctionSlot, amount: int, manor: Manor = None) -> None:
    """
    验证出价金额是否合法

    维克里拍卖中：
    - 首次出价：需要 >= 起拍价
    - 加价：需要 > 当前自己的出价

    Args:
        slot: 拍卖位
        amount: 出价金额
        manor: 出价者庄园（可选，用于检查是否已有出价）

    Raises:
        ValueError: 出价金额不合法时抛出
    """
    # 如果还没有人出价，可以按起拍价出价
    if slot.bid_count == 0:
        min_bid = slot.starting_price
        if amount < min_bid:
            raise ValueError(f"出价金额不得低于起拍价 {min_bid} 金条")
        return

    # 如果已有出价，检查是否为加价
    if manor:
        my_bid = AuctionBid.objects.filter(
            slot=slot, manor=manor, status=AuctionBid.Status.ACTIVE
        ).first()
        if my_bid:
            # 已有出价，需要比自己之前的出价高
            if amount <= my_bid.amount:
                raise ValueError(f"加价金额必须高于您之前的出价 {my_bid.amount} 金条")
            return

    # 新出价者，需要高于当前最低中标价才有意义
    cutoff = get_cutoff_price(slot)
    ranking = get_slot_ranking(slot)
    winner_count = slot.quantity

    if len(ranking) >= winner_count and amount <= cutoff:
        raise ValueError(
            f"出价金额需要高于当前最低中标价 {cutoff} 金条才能进入前 {winner_count} 名"
        )


def place_bid(manor: Manor, slot_id: int, amount: int) -> Tuple[AuctionBid, bool]:
    """
    玩家出价（维克里拍卖）

    使用 select_for_update 锁定拍卖位防止并发问题。
    如果玩家之前有出价，会先解冻之前的金条再冻结新金额。
    只有被挤出前N名（N=slot.quantity）的玩家才会被退还金条。

    Args:
        manor: 出价者庄园
        slot_id: 拍卖位ID
        amount: 出价金额（金条）

    Returns:
        Tuple[AuctionBid, bool]: (出价记录, 是否为首次出价)

    Raises:
        ValueError: 验证失败时抛出
    """
    outbid_player = None  # 被挤出前N名的玩家

    with transaction.atomic():
        # 锁定拍卖位
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

        # 验证出价金额
        validate_bid_amount(slot, amount, manor)

        # 查找该玩家之前在此拍卖位的有效出价
        previous_bid = (
            AuctionBid.objects.select_for_update()
            .filter(
                slot=slot,
                manor=manor,
                status=AuctionBid.Status.ACTIVE,
            )
            .first()
        )

        # 计算需要额外冻结的金条数
        previous_frozen = 0
        if previous_bid and hasattr(previous_bid, "frozen_record"):
            try:
                previous_frozen = previous_bid.frozen_record.amount
            except FrozenGoldBar.DoesNotExist:
                pass

        additional_needed = amount - previous_frozen

        # 验证可用金条是否足够
        available = get_available_gold_bars(manor)
        if additional_needed > available:
            raise ValueError(
                f"可用金条不足，当前可用 {available} 根，"
                f"还需要 {additional_needed} 根"
            )

        # 如果有之前的出价，解冻之前的金条并标记旧出价
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

        # 获取出价前的排名情况（用于判断谁会被挤出）
        winner_count = slot.quantity
        ranking_before = get_slot_ranking(slot)

        # 如果已满员，记录当前第N名（可能会被挤出）
        player_to_kick = None
        if len(ranking_before) >= winner_count:
            player_to_kick = ranking_before[winner_count - 1]

        # 创建新出价记录
        new_bid = AuctionBid.objects.create(
            slot=slot,
            manor=manor,
            amount=amount,
            status=AuctionBid.Status.ACTIVE,
        )

        # 冻结金条
        freeze_gold_bars(manor, amount, new_bid)

        # 更新出价次数
        slot.bid_count += 1

        # 重新获取排名，判断是否有人被挤出
        ranking_after = get_slot_ranking(slot)

        # 检查之前的第N名是否被挤出了
        if player_to_kick and player_to_kick.manor_id != manor.id:
            # 检查他是否还在前N名中
            still_in = False
            for i, bid in enumerate(ranking_after):
                if i >= winner_count:
                    break
                if bid.id == player_to_kick.id:
                    still_in = True
                    break

            if not still_in:
                # 被挤出了，退还金条
                outbid_player = player_to_kick.manor
                player_to_kick.status = AuctionBid.Status.OUTBID
                player_to_kick.save(update_fields=["status"])
                try:
                    if player_to_kick.frozen_record:
                        unfreeze_gold_bars(player_to_kick.frozen_record)
                except FrozenGoldBar.DoesNotExist:
                    pass

        # 更新 current_price 为当前最低中标价（便于前端显示）
        slot.current_price = get_cutoff_price(slot)

        # 更新 highest_bidder 为当前第一名（便于兼容旧逻辑）
        if ranking_after:
            slot.highest_bidder = ranking_after[0].manor
        else:
            slot.highest_bidder = manor

        slot.save(update_fields=["current_price", "highest_bidder", "bid_count"])

    # 事务外发送通知，减少锁持有时间
    if outbid_player:
        _notify_outbid_vickrey(outbid_player, slot, amount, manor, winner_count)

    return new_bid, is_first_bid


def _notify_outbid_vickrey(
    manor: Manor, slot: AuctionSlot, new_price: int, new_bidder: Manor, winner_count: int
) -> None:
    """通知玩家被挤出中标范围（维克里拍卖）"""
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

    # WebSocket 即时推送
    channel_layer = get_channel_layer()
    if channel_layer:
        payload = {
            "kind": "auction_outbid",
            "title": "【拍卖行】您已被挤出中标范围",
            "item_name": slot.item_template.name,
            "item_key": slot.item_template.key,
            "new_price": new_price,
            "winner_count": winner_count,
        }
        try:
            async_to_sync(channel_layer.group_send)(
                f"user_{manor.user_id}",
                {"type": "notify.message", "payload": payload},
            )
        except Exception:
            logger.warning(
                f"Failed to send auction outbid notification to user {manor.user_id}",
                exc_info=True,
            )


def _notify_outbid(
    manor: Manor, slot: AuctionSlot, new_price: int, new_bidder: Manor
) -> None:
    """通知玩家被超越"""
    create_message(
        manor=manor,
        kind="system",
        title="【拍卖行】您的出价已被超越",
        body=(
            f"在 {slot.item_template.name} 的拍卖中，您的出价已被超越！\n\n"
            f"最新价格：{new_price} 金条\n"
            f"最高出价者：{new_bidder.name}\n\n"
            f"您冻结的金条已自动退还，如需继续竞拍请尽快加价。"
        ),
    )

    # WebSocket 即时推送
    channel_layer = get_channel_layer()
    if channel_layer:
        payload = {
            "kind": "auction_outbid",
            "title": "【拍卖行】您的出价已被超越",
            "item_name": slot.item_template.name,
            "item_key": slot.item_template.key,
            "new_price": new_price,
        }
        try:
            async_to_sync(channel_layer.group_send)(
                f"user_{manor.user_id}",
                {"type": "notify.message", "payload": payload},
            )
        except Exception:
            logger.warning(
                f"Failed to send auction outbid notification to user {manor.user_id}",
                exc_info=True,
            )


# ============ 结算逻辑 ============


def settle_auction_round(round_id: int = None) -> Dict:
    """
    结算拍卖轮次

    Args:
        round_id: 轮次ID，如果不传则结算当前到期的轮次

    Returns:
        结算统计信息
    """
    stats = {"settled": 0, "sold": 0, "unsold": 0, "total_gold_bars": 0}

    with transaction.atomic():
        # 获取要结算的轮次
        if round_id:
            auction_round = (
                AuctionRound.objects.select_for_update()
                .filter(id=round_id, status=AuctionRound.Status.ACTIVE)
                .first()
            )
        else:
            # 查找已到期但未结算的轮次
            auction_round = (
                AuctionRound.objects.select_for_update()
                .filter(
                    status=AuctionRound.Status.ACTIVE,
                    end_at__lte=timezone.now(),
                )
                .first()
            )

        if not auction_round:
            logger.info("没有需要结算的拍卖轮次")
            return stats

        # 标记为结算中
        auction_round.status = AuctionRound.Status.SETTLING
        auction_round.save(update_fields=["status"])

    # 遍历拍卖位进行结算（每个拍卖位单独事务）
    slots = AuctionSlot.objects.filter(
        round=auction_round, status=AuctionSlot.Status.ACTIVE
    ).select_related("item_template", "highest_bidder")

    for slot in slots:
        try:
            result = _settle_slot(slot)
            if result["sold"]:
                stats["sold"] += 1
                stats["total_gold_bars"] += result["price"]
            else:
                stats["unsold"] += 1
        except Exception as e:
            logger.exception(f"结算拍卖位 {slot.id} 时出错：{e}")
            continue

    # 标记轮次为已完成
    with transaction.atomic():
        auction_round.status = AuctionRound.Status.COMPLETED
        auction_round.settled_at = timezone.now()
        auction_round.save(update_fields=["status", "settled_at"])

    stats["settled"] = 1
    logger.info(
        f"拍卖轮次 #{auction_round.round_number} 结算完成，"
        f"售出 {stats['sold']} 件，流拍 {stats['unsold']} 件，"
        f"共收取 {stats['total_gold_bars']} 金条"
    )

    return stats


def _settle_slot(slot: AuctionSlot) -> Dict:
    """
    结算单个拍卖位（维克里拍卖）

    维克里拍卖结算规则：
    - 前 N 名出价者各中标（N = slot.quantity）
    - 所有中标者支付统一价格（第 N 名的出价）
    - 每人获得 1 个物品
    - 多冻结的金条退还
    """
    result = {"sold": False, "price": 0, "winner_count": 0}

    with transaction.atomic():
        # 锁定拍卖位
        slot = AuctionSlot.objects.select_for_update().get(pk=slot.pk)

        # 获取出价排名
        ranking = get_slot_ranking(slot)
        winner_count = slot.quantity  # 中标名额数

        if not ranking:
            # 流拍：没有人出价
            slot.status = AuctionSlot.Status.UNSOLD
            slot.save(update_fields=["status"])
            return result

        # 确定实际中标人数和结算价格
        actual_winners = ranking[:winner_count]  # 前N名
        actual_winner_count = len(actual_winners)

        # 结算价格 = 第N名的出价（如果不足N人，则为最后一名的出价）
        settlement_price = actual_winners[-1].amount

        # 处理每个中标者
        for winning_bid in actual_winners:
            winner = winning_bid.manor

            # 处理金条：只扣结算价，多余的退还
            frozen_amount = winning_bid.frozen_gold_bars
            refund_amount = frozen_amount - settlement_price

            if refund_amount > 0:
                # 需要退还部分金条：先解冻全部，再只消耗结算价
                _partial_consume_frozen_gold_bars(
                    winning_bid, winner, settlement_price, refund_amount
                )
            else:
                # 刚好或不足（理论上不会不足），直接消耗
                try:
                    if winning_bid.frozen_record:
                        consume_frozen_gold_bars(winning_bid.frozen_record, winner)
                except FrozenGoldBar.DoesNotExist:
                    pass

            # 更新出价状态为中标
            winning_bid.status = AuctionBid.Status.WON
            winning_bid.save(update_fields=["status"])

            # 发送中标通知（每人获得1个物品）
            _send_winning_notification_vickrey(
                slot, winner, settlement_price, actual_winner_count
            )

            result["price"] += settlement_price

        result["sold"] = True
        result["winner_count"] = actual_winner_count

        # 退还未中标者的金条（如果有的话，理论上在出价时已处理）
        for losing_bid in ranking[winner_count:]:
            try:
                if losing_bid.frozen_record and losing_bid.frozen_record.is_frozen:
                    unfreeze_gold_bars(losing_bid.frozen_record)
            except FrozenGoldBar.DoesNotExist:
                pass

        # 更新拍卖位状态
        slot.status = AuctionSlot.Status.SOLD
        slot.save(update_fields=["status"])

    return result


def _partial_consume_frozen_gold_bars(
    bid: AuctionBid, manor: Manor, consume_amount: int, refund_amount: int
) -> None:
    """
    部分消耗冻结金条（用于维克里拍卖，出价高于结算价的情况）

    Args:
        bid: 出价记录
        manor: 庄园
        consume_amount: 实际扣除的金条数
        refund_amount: 退还的金条数
    """
    from gameplay.services.inventory import consume_inventory_item

    try:
        frozen_record = bid.frozen_record
    except FrozenGoldBar.DoesNotExist:
        return

    if not frozen_record or not frozen_record.is_frozen:
        return

    # 实际只扣除结算价格的金条
    consume_inventory_item(manor, GOLD_BAR_ITEM_KEY, consume_amount)

    # 更新冻结记录
    frozen_record.is_frozen = False
    frozen_record.unfrozen_at = timezone.now()
    frozen_record.save(update_fields=["is_frozen", "unfrozen_at"])

    logger.info(
        f"维克里拍卖结算: 庄园 {manor.id} 实际扣除 {consume_amount} 金条，"
        f"退还 {refund_amount} 金条"
    )


def _send_winning_notification_vickrey(
    slot: AuctionSlot, winner: Manor, settlement_price: int, total_winners: int
) -> None:
    """发送中标通知并发放物品（维克里拍卖，每人1个）"""
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
            "items": {slot.item_template.key: 1},  # 每人获得1个
        },
    )

    # WebSocket 即时推送
    channel_layer = get_channel_layer()
    if channel_layer:
        payload = {
            "kind": "auction_won",
            "title": "【拍卖行】恭喜您成功拍得物品",
            "item_name": slot.item_template.name,
            "item_key": slot.item_template.key,
            "quantity": 1,
            "price": settlement_price,
            "total_winners": total_winners,
        }
        try:
            async_to_sync(channel_layer.group_send)(
                f"user_{winner.user_id}",
                {"type": "notify.message", "payload": payload},
            )
        except Exception:
            logger.warning(
                f"Failed to send auction won notification to user {winner.user_id}",
                exc_info=True,
            )


# ============ 查询接口 ============


def get_active_slots(
    category: str = None,
    rarity: str = None,
    order_by: str = "-current_price",
) -> QuerySet:
    """
    获取当前活跃的拍卖位列表

    Args:
        category: 物品类别筛选
        rarity: 稀有度筛选
        order_by: 排序字段

    Returns:
        拍卖位查询集
    """
    current_round = get_current_round()
    if not current_round:
        return AuctionSlot.objects.none()

    queryset = AuctionSlot.objects.filter(
        round=current_round,
        status=AuctionSlot.Status.ACTIVE,
    ).select_related("item_template", "highest_bidder", "round")

    # 类别筛选
    if category and category != "all":
        tool_effect_types = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}
        if category in tool_effect_types:
            queryset = queryset.filter(
                item_template__effect_type__in=tool_effect_types
            )
        else:
            queryset = queryset.filter(item_template__effect_type=category)

    # 稀有度筛选
    if rarity and rarity != "all":
        queryset = queryset.filter(item_template__rarity=rarity)

    return queryset.order_by(order_by)


def get_my_bids(manor: Manor, include_history: bool = False) -> QuerySet:
    """
    获取我的出价记录

    Args:
        manor: 庄园
        include_history: 是否包含历史记录

    Returns:
        出价记录查询集
    """
    queryset = AuctionBid.objects.filter(manor=manor).select_related(
        "slot__item_template", "slot__round", "slot__highest_bidder"
    )

    if not include_history:
        # 只显示当前轮次的出价
        current_round = get_current_round()
        if current_round:
            queryset = queryset.filter(slot__round=current_round)
        else:
            return AuctionBid.objects.none()

    return queryset.order_by("-created_at")


def get_my_leading_bids(manor: Manor) -> List[AuctionSlot]:
    """
    获取我当前在中标范围内的拍卖位（维克里拍卖）

    Args:
        manor: 庄园

    Returns:
        我在中标范围内的拍卖位列表
    """
    current_round = get_current_round()
    if not current_round:
        return []

    # 获取我有有效出价的所有拍卖位
    my_active_bids = AuctionBid.objects.filter(
        manor=manor,
        status=AuctionBid.Status.ACTIVE,
        slot__round=current_round,
        slot__status=AuctionSlot.Status.ACTIVE,
    ).select_related("slot", "slot__item_template")

    result = []
    for bid in my_active_bids:
        if is_in_winning_range(bid.slot, manor):
            result.append(bid.slot)

    return result


def get_my_safe_slots_count(manor: Manor) -> int:
    """
    获取我当前在中标范围内的拍卖位数量（维克里拍卖）

    Args:
        manor: 庄园

    Returns:
        在中标范围内的数量
    """
    return len(get_my_leading_bids(manor))


def get_slot_bid_info(slot: AuctionSlot, manor: Manor = None) -> Dict:
    """
    获取拍卖位的出价信息（维克里拍卖，不含具体排名）

    Args:
        slot: 拍卖位
        manor: 庄园（可选，用于判断自己是否在中标范围）

    Returns:
        包含中标名额、出价人数、最低中标价、是否安全等信息的字典
    """
    ranking = get_slot_ranking(slot)
    winner_count = slot.quantity  # 中标名额数
    bidder_count = len(ranking)
    cutoff_price = get_cutoff_price(slot)

    info = {
        "winner_count": winner_count,  # 中标名额数
        "bidder_count": bidder_count,  # 当前出价人数
        "cutoff_price": cutoff_price,  # 当前最低中标价
        "is_full": bidder_count >= winner_count,  # 名额是否已满
        "my_bid_amount": None,  # 我的出价金额
        "is_safe": None,  # 我是否在中标范围内
    }

    if manor:
        # 查找我的出价
        my_bid = next((b for b in ranking if b.manor_id == manor.id), None)
        if my_bid:
            info["my_bid_amount"] = my_bid.amount
            info["is_safe"] = is_in_winning_range(slot, manor)

    return info


def get_auction_stats(manor: Manor = None) -> Dict:
    """
    获取拍卖行统计信息（维克里拍卖）

    Args:
        manor: 庄园（可选，用于获取个人统计）

    Returns:
        统计信息字典
    """
    current_round = get_current_round()

    stats = {
        "current_round": None,
        "time_remaining": 0,
        "total_slots": 0,
        "active_slots": 0,
        "my_leading_count": 0,  # 我在中标范围内的数量
        "my_frozen_gold_bars": 0,
        "available_gold_bars": 0,
    }

    if current_round:
        stats["current_round"] = current_round.round_number
        stats["time_remaining"] = current_round.time_remaining
        stats["total_slots"] = current_round.slots.count()
        stats["active_slots"] = current_round.slots.filter(
            status=AuctionSlot.Status.ACTIVE
        ).count()

    if manor:
        if current_round:
            # 维克里拍卖：计算在中标范围内的数量
            stats["my_leading_count"] = get_my_safe_slots_count(manor)

        stats["my_frozen_gold_bars"] = get_frozen_gold_bars(manor)
        stats["available_gold_bars"] = get_available_gold_bars(manor)

    return stats
