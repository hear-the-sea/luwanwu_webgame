"""
交易行服务层
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.config import TRADE
from core.utils.yaml_loader import load_yaml_data
from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from gameplay.models.items import LEGACY_TOOL_EFFECT_TYPES
from gameplay.services.resources import grant_resources_locked, spend_resources_locked
from gameplay.services.utils.messages import create_message
from gameplay.services.utils.notifications import notify_user
from trade.models import MarketListing, MarketTransaction
from trade.services.market_expiration import expire_listings_queryset as _expire_listings_queryset_impl
from trade.services.market_listing_helpers import (
    create_listing_record,
    decrement_listing_inventory,
    load_tradeable_item_template,
    lock_listing_inventory_item,
    normalize_listing_inputs,
    validate_gold_bar_availability,
    validate_listing_inventory,
    validate_listing_total_price,
)
from trade.services.market_notification_helpers import build_cancel_listing_result as _build_cancel_listing_result_impl
from trade.services.market_notification_helpers import (
    restore_cancelled_listing_inventory as _restore_cancelled_listing_inventory_impl,
)
from trade.services.market_notification_helpers import send_purchase_notifications as _send_purchase_notifications_impl
from trade.services.market_purchase_helpers import (
    get_locked_listing_for_purchase as _get_locked_listing_for_purchase_impl,
)
from trade.services.market_purchase_helpers import (
    grant_listing_item_to_buyer_locked as _grant_listing_item_to_buyer_locked_impl,
)
from trade.services.market_purchase_helpers import lock_purchase_parties as _lock_purchase_parties_impl
from trade.services.market_purchase_helpers import validate_listing_for_purchase as _validate_listing_for_purchase_impl
from trade.services.market_rules import DEFAULT_TRADE_MARKET_RULES
from trade.services.market_rules import normalize_trade_market_rules as _normalize_trade_market_rules

logger = logging.getLogger(__name__)
_build_cancel_listing_result = _build_cancel_listing_result_impl
_restore_cancelled_listing_inventory = _restore_cancelled_listing_inventory_impl

TRADE_MARKET_RULES_PATH = Path(settings.BASE_DIR) / "data" / "trade_market_rules.yaml"


@lru_cache(maxsize=1)
def load_trade_market_rules() -> dict[str, dict[int, int]]:
    raw = load_yaml_data(
        TRADE_MARKET_RULES_PATH,
        logger=logger,
        context="trade market rules",
        default=DEFAULT_TRADE_MARKET_RULES,
    )
    return _normalize_trade_market_rules(raw)


def clear_trade_market_rules_cache() -> None:
    global LISTING_FEES
    load_trade_market_rules.cache_clear()
    LISTING_FEES = dict(load_trade_market_rules()["listing_fees"])


# 手续费配置
LISTING_FEES = dict(load_trade_market_rules()["listing_fees"])

# 从 core.config 导入配置
TRANSACTION_TAX_RATE = TRADE.TRANSACTION_TAX_RATE
MIN_PRICE_MULTIPLIER = TRADE.MIN_PRICE_MULTIPLIER
MAX_PRICE = TRADE.MAX_PRICE
MAX_TOTAL_PRICE = TRADE.MAX_TOTAL_PRICE

ALLOWED_LISTING_ORDER_BY = {
    "listed_at",
    "-listed_at",
    "unit_price",
    "-unit_price",
    "price",
    "-price",
    "total_price",
    "-total_price",
    "quantity",
    "-quantity",
    "expires_at",
    "-expires_at",
}


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_create_message(**kwargs) -> bool:
    try:
        create_message(**kwargs)
    except Exception as exc:
        logger.warning("market create_message failed: %s", exc, exc_info=True)
        return False
    return True


def _safe_notify_user(user_id: int, payload: dict, *, log_context: str) -> None:
    try:
        notify_user(user_id, payload, log_context=log_context)
    except Exception as exc:
        logger.warning("market notify_user failed: user_id=%s error=%s", user_id, exc, exc_info=True)


def get_listing_fee(duration: int) -> int:
    """
    获取上架手续费

    Args:
        duration: 上架时长（秒）

    Returns:
        手续费金额
    """
    return LISTING_FEES.get(duration, 5000)


def validate_listing_price(item_template: ItemTemplate, unit_price: int) -> None:
    """
    验证定价是否合法

    Args:
        item_template: 物品模板
        unit_price: 单价

    Raises:
        ValueError: 如果价格不合法
    """
    template_price = max(0, _safe_int(getattr(item_template, "price", 0), 0))
    normalized_unit_price = _safe_int(unit_price, -1)
    min_price = int(template_price * MIN_PRICE_MULTIPLIER)
    if normalized_unit_price < min_price:
        raise ValueError(f"单价不能低于 {min_price} 银两")

    if normalized_unit_price > MAX_PRICE:
        raise ValueError(f"单价不能超过 {MAX_PRICE:,} 银两")


def create_listing(
    manor: Manor,
    item_key: str,
    quantity: int,
    unit_price: int,
    duration: int,
) -> MarketListing:
    """
    创建交易行挂单（并发安全版本）

    使用数据库行锁和F()表达式确保并发安全：
    - 锁定Manor行防止银两透支
    - 锁定InventoryItem行防止物品超卖
    - 使用F()表达式进行原子性数值更新

    Args:
        manor: 卖家庄园
        item_key: 物品key
        quantity: 数量
        unit_price: 单价
        duration: 上架时长（秒）

    Returns:
        创建的挂单对象

    Raises:
        ValueError: 验证失败时抛出异常
    """
    quantity, unit_price, duration = normalize_listing_inputs(quantity, unit_price, duration, safe_int=_safe_int)

    # 验证时长
    if duration not in LISTING_FEES:
        raise ValueError(f"无效的上架时长，请选择 {list(LISTING_FEES.keys())}")

    # 获取物品模板
    item_template = load_tradeable_item_template(item_template_model=ItemTemplate, item_key=item_key)

    # 验证价格
    validate_listing_price(item_template, unit_price)

    # 验证数量
    if quantity <= 0:
        raise ValueError("数量必须大于0")

    # 并发安全的事务处理
    with transaction.atomic():
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
        listing_fee = get_listing_fee(duration)

        # 步骤1：消耗手续费（已包含并发安全检查和资源验证）
        spend_resources_locked(
            locked_manor,
            {"silver": listing_fee},
            note="交易行挂单手续费",
            reason=ResourceEvent.Reason.MARKET_LISTING_FEE,
        )

        # 步骤2：锁定物品库存行并验证数量
        # IMPORTANT: 必须指定storage_location避免仓库和藏宝阁的同名物品冲突
        inventory_item = lock_listing_inventory_item(
            inventory_item_model=InventoryItem,
            locked_manor=locked_manor,
            item_template=item_template,
        )
        validate_listing_inventory(inventory_item=inventory_item, quantity=quantity)

        # 金条需要特殊检查：考虑拍卖冻结的金条
        if item_template.key == "gold_bar":
            from .auction_service import get_frozen_gold_bars

            frozen = get_frozen_gold_bars(manor)
            validate_gold_bar_availability(inventory_item=inventory_item, quantity=quantity, frozen=frozen)

        # 步骤3：使用F()表达式+条件约束原子性扣减库存
        # quantity__gte条件确保不会扣成负数（双重保险）
        decrement_listing_inventory(
            inventory_item_model=InventoryItem, inventory_item=inventory_item, quantity=quantity
        )

        # 步骤4：创建挂单记录
        total_price = validate_listing_total_price(
            unit_price=unit_price,
            quantity=quantity,
            max_total_price=MAX_TOTAL_PRICE,
        )

        listing = create_listing_record(
            market_listing_model=MarketListing,
            locked_manor=locked_manor,
            item_template=item_template,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
            duration=duration,
            listing_fee=listing_fee,
        )

    return listing


def get_active_listings(
    item_template_id: int = None,
    order_by: str = "-listed_at",
    category: str = None,
    rarity: str = None,
) -> QuerySet:
    """
    获取在售挂单列表

    Args:
        item_template_id: 物品模板ID（可选）
        order_by: 排序字段
        category: 物品类别筛选
        rarity: 稀有度筛选

    Returns:
        挂单查询集
    """
    queryset = MarketListing.objects.filter(
        status=MarketListing.Status.ACTIVE,
        expires_at__gt=timezone.now(),
    ).select_related("seller__user", "item_template")

    if item_template_id:
        queryset = queryset.filter(item_template_id=item_template_id)

    if category and category != "all":
        if category in LEGACY_TOOL_EFFECT_TYPES:
            queryset = queryset.filter(item_template__effect_type__in=LEGACY_TOOL_EFFECT_TYPES)
        else:
            queryset = queryset.filter(item_template__effect_type=category)

    if rarity and rarity != "all":
        queryset = queryset.filter(item_template__rarity=rarity)

    safe_order_by = order_by if order_by in ALLOWED_LISTING_ORDER_BY else "-listed_at"
    return queryset.order_by(safe_order_by)


def _get_locked_listing_for_purchase(listing_id: int) -> MarketListing:
    return _get_locked_listing_for_purchase_impl(market_listing_model=MarketListing, listing_id=listing_id)


def _validate_listing_for_purchase(listing: MarketListing, buyer: Manor) -> None:
    _validate_listing_for_purchase_impl(listing, buyer, active_status=MarketListing.Status.ACTIVE)


def _lock_purchase_parties(buyer_pk: int, seller_pk: int | None) -> tuple[Manor, Manor | None]:
    return _lock_purchase_parties_impl(manor_model=Manor, buyer_pk=buyer_pk, seller_pk=seller_pk)


def _grant_listing_item_to_buyer_locked(buyer_locked: Manor, item_template: ItemTemplate, quantity: int) -> None:
    _grant_listing_item_to_buyer_locked_impl(
        inventory_item_model=InventoryItem,
        buyer_locked=buyer_locked,
        item_template=item_template,
        quantity=quantity,
    )


def _send_purchase_notifications(
    *,
    buyer: Manor,
    listing: MarketListing,
    tax_amount: int,
    seller_received: int,
) -> tuple[bool, bool]:
    return _send_purchase_notifications_impl(
        buyer=buyer,
        listing=listing,
        tax_amount=tax_amount,
        seller_received=seller_received,
        safe_create_message=_safe_create_message,
        safe_notify_user=_safe_notify_user,
    )


def purchase_listing(buyer: Manor, listing_id: int) -> MarketTransaction:
    """
    购买挂单物品（并发安全版本）

    使用数据库行锁和F()表达式确保并发安全：
    - 锁定MarketListing防止重复购买
    - 锁定买家和卖家Manor防止银两透支/覆盖
    - 锁定买家InventoryItem防止物品发放时的并发冲突
    - 使用F()表达式进行原子性数值更新

    锁定顺序：MarketListing -> 买家Manor -> 卖家Manor -> 买家InventoryItem
    这个顺序与上架路径不同，但通过Listing作为第一锁避免了循环等待

    Args:
        buyer: 买家庄园
        listing_id: 挂单ID

    Returns:
        交易记录对象

    Raises:
        ValueError: 验证失败时抛出异常
    """
    with transaction.atomic():
        listing = _get_locked_listing_for_purchase(listing_id)
        _validate_listing_for_purchase(listing, buyer)
        buyer_locked, seller_locked = _lock_purchase_parties(buyer.pk, listing.seller_id)

        spend_resources_locked(
            buyer_locked,
            {"silver": listing.total_price},
            note=f"购买{listing.item_template.name}",
            reason=ResourceEvent.Reason.MARKET_PURCHASE,
        )

        tax_amount = int(listing.total_price * TRANSACTION_TAX_RATE)
        seller_received = listing.total_price - tax_amount

        if seller_locked is not None:
            grant_resources_locked(
                seller_locked,
                {"silver": seller_received},
                note=f"出售{listing.item_template.name}",
                reason=ResourceEvent.Reason.ITEM_SOLD,
                sync_production=False,
            )

        now = timezone.now()
        listing.status = MarketListing.Status.SOLD
        listing.buyer = buyer_locked
        listing.sold_at = now
        listing.save(update_fields=["status", "buyer", "sold_at"])

        transaction_record = MarketTransaction.objects.create(
            listing=listing,
            buyer=buyer_locked,
            total_price=listing.total_price,
            tax_amount=tax_amount,
            seller_received=seller_received,
        )

        _grant_listing_item_to_buyer_locked(buyer_locked, listing.item_template, listing.quantity)

    buyer_mail_sent, seller_mail_sent = _send_purchase_notifications(
        buyer=buyer,
        listing=listing,
        tax_amount=tax_amount,
        seller_received=seller_received,
    )

    transaction_record.buyer_mail_sent = buyer_mail_sent
    transaction_record.seller_mail_sent = seller_mail_sent
    transaction_record.save(update_fields=["buyer_mail_sent", "seller_mail_sent"])

    return transaction_record


@transaction.atomic
def cancel_listing(manor: Manor, listing_id: int) -> Dict:
    """
    取消挂单（仅限卖家本人）

    Args:
        manor: 卖家庄园
        listing_id: 挂单ID

    Returns:
        取消结果字典

    Raises:
        ValueError: 验证失败时抛出异常
    """
    listing = (
        MarketListing.objects.select_for_update()
        .select_related("item_template")
        .filter(id=listing_id, seller=manor)
        .first()
    )

    if not listing:
        raise ValueError("挂单不存在或无权取消")

    if listing.status != MarketListing.Status.ACTIVE:
        raise ValueError("该挂单已经不在售状态，无法取消")

    listing.status = MarketListing.Status.CANCELLED
    listing.save(update_fields=["status"])

    _restore_cancelled_listing_inventory(
        inventory_item_model=InventoryItem,
        manor=manor,
        listing=listing,
    )
    return _build_cancel_listing_result(listing=listing)


def _expire_listings_queryset(expired_listings: QuerySet, log_label: str, limit: int | None = None) -> int:
    return _expire_listings_queryset_impl(
        expired_listings,
        log_label,
        market_listing_model=MarketListing,
        create_message_func=create_message,
        notify_user_func=notify_user,
        logger=logger,
        limit=limit,
    )


def expire_listings(limit: int = 1000) -> int:
    """
    处理过期挂单，通过邮件退回物品并删除挂单记录

    Args:
        limit: 单次最大处理数量（默认1000），防止定时任务超时

    Returns:
        处理的挂单数量
    """
    expired_listings = MarketListing.objects.filter(
        status=MarketListing.Status.ACTIVE,
        expires_at__lte=timezone.now(),
    )
    return _expire_listings_queryset(expired_listings, "处理过期挂单", limit=limit)


def expire_user_listings(manor: Manor) -> int:
    """
    处理指定用户的过期挂单（用户访问交易行时主动触发）

    Args:
        manor: 庄园

    Returns:
        处理的挂单数量
    """
    expired_listings = MarketListing.objects.filter(
        seller=manor,
        status=MarketListing.Status.ACTIVE,
        expires_at__lte=timezone.now(),
    )
    return _expire_listings_queryset(expired_listings, f"处理用户 {manor.id} 的过期挂单")


def get_my_listings(manor: Manor, status: str = None) -> QuerySet:
    """
    获取我的挂单

    Args:
        manor: 庄园
        status: 状态筛选（可选）

    Returns:
        挂单查询集
    """
    queryset = MarketListing.objects.filter(seller=manor).select_related("item_template", "buyer__user")

    if status and status != "all":
        queryset = queryset.filter(status=status)

    return queryset.order_by("-listed_at")


def get_market_stats() -> Dict:
    """
    获取交易行统计信息

    Returns:
        统计信息字典
    """
    active_count = MarketListing.objects.filter(status=MarketListing.Status.ACTIVE).count()

    sold_today = MarketTransaction.objects.filter(transaction_at__date=timezone.now().date()).count()

    return {
        "active_count": active_count,
        "sold_today": sold_today,
    }


def get_tradeable_inventory(manor: Manor) -> QuerySet:
    """
    获取可上架的物品列表

    IMPORTANT: Only show WAREHOUSE items since create_listing only operates on WAREHOUSE.

    Args:
        manor: 庄园

    Returns:
        可交易的库存物品查询集
    """
    return InventoryItem.objects.filter(
        manor=manor,
        template__tradeable=True,
        quantity__gt=0,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).select_related("template")
