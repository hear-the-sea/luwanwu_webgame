"""
交易行服务层
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict

from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from gameplay.services.messages import create_message
from gameplay.services.notifications import notify_user
from gameplay.services.resources import grant_resources_locked, spend_resources_locked
from trade.models import MarketListing, MarketTransaction

logger = logging.getLogger(__name__)

# 手续费配置
LISTING_FEES = {
    7200: 5000,  # 2小时 -> 5000银两
    28800: 10000,  # 8小时 -> 10000银两
    86400: 20000,  # 24小时 -> 20000银两
}

# 税率
TRANSACTION_TAX_RATE = 0.10  # 10%

# 价格限制
MIN_PRICE_MULTIPLIER = 1.0  # 最低价格为物品price的1倍
MAX_PRICE = 10000000  # 最高1000万银两

ALLOWED_LISTING_ORDER_BY = {
    "listed_at",
    "-listed_at",
    "unit_price",
    "-unit_price",
    "total_price",
    "-total_price",
    "quantity",
    "-quantity",
    "expires_at",
    "-expires_at",
}


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
    min_price = int(item_template.price * MIN_PRICE_MULTIPLIER)
    if unit_price < min_price:
        raise ValueError(f"单价不能低于 {min_price} 银两")

    if unit_price > MAX_PRICE:
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
    # 验证时长
    if duration not in LISTING_FEES:
        raise ValueError(f"无效的上架时长，请选择 {list(LISTING_FEES.keys())}")

    # 获取物品模板
    item_template = ItemTemplate.objects.filter(key=item_key).first()
    if not item_template:
        raise ValueError("物品不存在")

    # 验证是否可交易
    if not item_template.tradeable:
        raise ValueError("该物品不可交易")

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
            reason=ResourceEvent.Reason.MARKET_LISTING_FEE
        )

        # 步骤2：锁定物品库存行并验证数量
        # IMPORTANT: 必须指定storage_location避免仓库和藏宝阁的同名物品冲突
        inventory_item = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=locked_manor,
                template=item_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )

        if not inventory_item or inventory_item.quantity < quantity:
            raise ValueError("物品数量不足")

        # 金条需要特殊检查：考虑拍卖冻结的金条
        if item_template.key == "gold_bar":
            from .auction_service import get_frozen_gold_bars

            frozen = get_frozen_gold_bars(manor)
            available = inventory_item.quantity - frozen
            if available < quantity:
                raise ValueError(f"可用金条不足（当前可用 {available} 个，{frozen} 个被拍卖冻结）")

        # 步骤3：使用F()表达式+条件约束原子性扣减库存
        # quantity__gte条件确保不会扣成负数（双重保险）
        updated_rows = InventoryItem.objects.filter(
            pk=inventory_item.pk, quantity__gte=quantity
        ).update(quantity=F("quantity") - quantity, updated_at=timezone.now())

        if not updated_rows:
            raise ValueError("物品数量不足或已被其他操作占用")

        # 步骤3.5：清理零库存记录，保持数据库整洁
        # 刷新对象以获取更新后的数量
        inventory_item.refresh_from_db()
        if inventory_item.quantity == 0:
            inventory_item.delete()

        # 步骤4：创建挂单记录
        total_price = unit_price * quantity
        expires_at = timezone.now() + timedelta(seconds=duration)

        listing = MarketListing.objects.create(
            seller=locked_manor,
            item_template=item_template,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
            duration=duration,
            listing_fee=listing_fee,
            expires_at=expires_at,
            status=MarketListing.Status.ACTIVE,
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
        tool_effect_types = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}
        if category in tool_effect_types:
            queryset = queryset.filter(item_template__effect_type__in=tool_effect_types)
        else:
            queryset = queryset.filter(item_template__effect_type=category)

    if rarity and rarity != "all":
        queryset = queryset.filter(item_template__rarity=rarity)

    safe_order_by = order_by if order_by in ALLOWED_LISTING_ORDER_BY else "-listed_at"
    return queryset.order_by(safe_order_by)


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
    # 并发安全的事务处理
    with transaction.atomic():
        # 步骤1：锁定挂单，防止重复购买
        listing = (
            MarketListing.objects.select_for_update()
            .select_related("seller__user", "item_template")
            .filter(id=listing_id)
            .first()
        )

        if not listing:
            raise ValueError("挂单不存在")

        # 验证挂单状态
        if listing.status != MarketListing.Status.ACTIVE:
            raise ValueError("该挂单已下架")

        if listing.is_expired:
            raise ValueError("该挂单已过期")

        if listing.seller == buyer:
            raise ValueError("不能购买自己的物品")

        # 步骤2：按固定顺序锁定买家/卖家庄园，避免隐式锁顺序导致的死锁风险
        buyer_locked = Manor.objects.select_for_update().get(pk=buyer.pk)
        seller_locked = Manor.objects.select_for_update().get(pk=listing.seller_id) if listing.seller_id else None

        # 步骤3：扣除买家银两
        spend_resources_locked(
            buyer_locked,
            {"silver": listing.total_price},
            note=f"购买{listing.item_template.name}",
            reason=ResourceEvent.Reason.MARKET_PURCHASE
        )

        # 步骤4：计算税费和卖家实收，发放卖家收益
        tax_amount = int(listing.total_price * TRANSACTION_TAX_RATE)
        seller_received = listing.total_price - tax_amount

        # 增加卖家银两（仅玩家卖家，系统商店无需处理）
        if seller_locked is not None:
            grant_resources_locked(
                seller_locked,
                {"silver": seller_received},
                note=f"出售{listing.item_template.name}",
                reason=ResourceEvent.Reason.ITEM_SOLD
            )

        # 步骤5：更新挂单状态
        now = timezone.now()
        listing.status = MarketListing.Status.SOLD
        listing.buyer = buyer_locked
        listing.sold_at = now
        listing.save(update_fields=["status", "buyer", "sold_at"])

        # 步骤6：创建交易记录
        transaction_record = MarketTransaction.objects.create(
            listing=listing,
            buyer=buyer_locked,
            total_price=listing.total_price,
            tax_amount=tax_amount,
            seller_received=seller_received,
        )

        # 步骤7：物品发放到买家仓库 - 锁定库存行防止并发冲突
        inventory_item = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=buyer_locked,
                template=listing.item_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )

        if inventory_item:
            # 已有该物品，使用F()表达式增加数量
            InventoryItem.objects.filter(pk=inventory_item.pk).update(
                quantity=F("quantity") + listing.quantity, updated_at=timezone.now()
            )
        else:
            # 首次获得该物品，创建新记录
            InventoryItem.objects.create(
                manor=buyer_locked,
                template=listing.item_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity=listing.quantity,
            )

    # 事务外发送邮件通知，减少锁持有时间
    # 买家通知（物品已直接添加到仓库，邮件仅作通知用途，不含附件）
    create_message(
        manor=buyer,
        kind="system",
        title="【交易成功】您购买的物品已送达",
        body=(
            f"恭喜！您成功购买了 {listing.item_template.name} x{listing.quantity}，"
            f"花费 {listing.total_price:,} 银两。\n\n"
            f"物品已直接存入您的仓库，请前往查看。\n\n"
            f"交易详情：\n"
            f"- 物品：{listing.item_template.name}\n"
            f"- 数量：{listing.quantity}\n"
            f"- 单价：{listing.unit_price:,} 银两\n"
            f"- 总价：{listing.total_price:,} 银两\n"
            f"- 卖家：{listing.seller.user.username}\n"
            f"- 成交时间：{listing.sold_at.strftime('%Y-%m-%d %H:%M:%S')}"
        ),
    )

    # 卖家通知（仅玩家卖家，银两已直接发放，邮件仅作通知）
    if listing.seller_id:
        create_message(
            manor=listing.seller,
            kind="system",
            title="【交易成功】您的物品已售出",
            body=(
                f"恭喜！您上架的 {listing.item_template.name} x{listing.quantity} 已成功售出！\n\n"
                f"银两已直接存入您的账户。\n\n"
                f"交易详情：\n"
                f"- 物品：{listing.item_template.name}\n"
                f"- 数量：{listing.quantity}\n"
                f"- 成交价：{listing.total_price:,} 银两\n"
                f"- 税费（10%）：{tax_amount:,} 银两\n"
                f"- 实际到账：{seller_received:,} 银两\n"
                f"- 买家：{buyer.user.username}\n"
                f"- 成交时间：{listing.sold_at.strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        )

        # WebSocket 即时推送通知卖家
        notify_user(
            listing.seller.user_id,
            {
                "kind": "market_sold",
                "title": "【交易成功】您的物品已售出",
                "item_name": listing.item_template.name,
                "item_key": listing.item_template.key,
                "quantity": listing.quantity,
                "silver_received": seller_received,
            },
            log_context="market sold notification",
        )

    # 标记邮件已发送
    transaction_record.buyer_mail_sent = True
    transaction_record.seller_mail_sent = True
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
    # 获取挂单
    listing = (
        MarketListing.objects.select_for_update()
        .select_related("item_template")
        .filter(id=listing_id, seller=manor)
        .first()
    )

    if not listing:
        raise ValueError("挂单不存在或无权取消")

    # 验证状态
    if listing.status != MarketListing.Status.ACTIVE:
        raise ValueError("该挂单已经不在售状态，无法取消")

    # 更新状态
    listing.status = MarketListing.Status.CANCELLED
    listing.save(update_fields=["status"])

    # 退回物品到仓库（使用原子操作防止并发丢失更新）
    # IMPORTANT: Must specify storage_location to avoid MultipleObjectsReturned
    # when the same template exists in both warehouse and treasury
    inventory_item = (
        InventoryItem.objects.select_for_update()
        .filter(
            manor=manor,
            template=listing.item_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .first()
    )

    if inventory_item:
        # 已有该物品，使用 F() 表达式增加数量
        InventoryItem.objects.filter(pk=inventory_item.pk).update(
            quantity=F("quantity") + listing.quantity, updated_at=timezone.now()
        )
    else:
        # 首次获得该物品，创建新记录
        InventoryItem.objects.create(
            manor=manor,
            template=listing.item_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity=listing.quantity,
        )

    return {
        "item_name": listing.item_template.name,
        "quantity": listing.quantity,
    }


def _expire_listings_queryset(expired_listings: QuerySet, log_label: str) -> int:
    """处理过期挂单，通过邮件退回物品并删除挂单记录。

    安全修复：先发送邮件确保物品退还成功，再删除挂单记录。
    避免邮件发送失败导致物品永久丢失。
    """
    count = 0
    for listing in expired_listings.select_for_update().select_related("seller", "item_template"):
        try:
            with transaction.atomic():
                # 保存挂单信息用于发送邮件（删除前先读取）
                seller = listing.seller
                item_template = listing.item_template
                item_name = item_template.name
                item_key = item_template.key
                quantity = listing.quantity
                unit_price = listing.unit_price
                listing_fee = listing.listing_fee
                listed_at = listing.listed_at
                expires_at = listing.expires_at

                # 安全修复：先将状态标记为过期（防止重复处理）
                listing.status = MarketListing.Status.EXPIRED
                listing.save(update_fields=["status"])

                # 通过邮件退回物品（如果失败会回滚状态变更）
                create_message(
                    manor=seller,
                    kind="system",
                    title="【交易过期】您的物品已退回",
                    body=(
                        f"您上架的 {item_name} x{quantity} 已过期，物品已通过附件退回。\n\n"
                        f"挂单信息：\n"
                        f"- 物品：{item_name}\n"
                        f"- 数量：{quantity}\n"
                        f"- 定价：{unit_price:,} 银两/件\n"
                        f"- 上架时间：{listed_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"- 过期时间：{expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"注意：手续费 {listing_fee:,} 银两不予退还。\n"
                        f"请在消息中领取附件以取回物品。"
                    ),
                    attachments={
                        "items": {item_key: quantity},
                    },
                )

                # 邮件发送成功后，删除挂单记录
                listing.delete()

                # WebSocket 即时推送通知卖家
                notify_user(
                    seller.user_id,
                    {
                        "kind": "market_expired",
                        "title": "【交易过期】您的物品已退回",
                        "item_name": item_name,
                        "item_key": item_key,
                        "quantity": quantity,
                    },
                    log_context="market expired notification",
                )

                count += 1
        except Exception as e:
            # 记录错误但继续处理其他挂单
            logger.exception(f"{log_label} {listing.id} 时出错：{e}")
            continue

    return count


def expire_listings() -> int:
    """
    处理过期挂单，通过邮件退回物品并删除挂单记录

    Returns:
        处理的挂单数量
    """
    expired_listings = MarketListing.objects.filter(
        status=MarketListing.Status.ACTIVE,
        expires_at__lte=timezone.now(),
    )
    return _expire_listings_queryset(expired_listings, "处理过期挂单")


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
    queryset = MarketListing.objects.filter(seller=manor).select_related(
        "item_template", "buyer__user"
    )

    if status and status != "all":
        queryset = queryset.filter(status=status)

    return queryset.order_by("-listed_at")


def get_market_stats() -> Dict:
    """
    获取交易行统计信息

    Returns:
        统计信息字典
    """
    active_count = MarketListing.objects.filter(
        status=MarketListing.Status.ACTIVE
    ).count()

    sold_today = MarketTransaction.objects.filter(
        transaction_at__date=timezone.now().date()
    ).count()

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
