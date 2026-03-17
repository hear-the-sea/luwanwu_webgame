"""
交易行服务层
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Dict

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from core.config import TRADE
from core.utils.yaml_loader import load_yaml_data
from gameplay.models import Manor
from gameplay.models.items import LEGACY_TOOL_EFFECT_TYPES
from trade.models import MarketListing, MarketTransaction
from trade.services import market_commands as _market_commands
from trade.services import market_facade as _market_facade
from trade.services import market_notification_helpers as _market_notification_helpers
from trade.services import market_purchase_helpers as _market_purchase_helpers
from trade.services import market_queries as _market_queries
from trade.services.market_expiration import expire_listings_queryset as _expire_listings_queryset_impl
from trade.services.market_listing_helpers import (
    create_listing_record,
    normalize_listing_inputs,
    validate_gold_bar_availability,
    validate_listing_inventory,
    validate_listing_total_price,
)
from trade.services.market_platform import (
    charge_listing_fee,
    decrement_market_listing_inventory,
    get_tradeable_inventory_queryset,
    grant_market_item_locked,
    load_market_item_template,
    lock_market_listing_inventory_item,
    pay_market_purchase,
    send_market_message,
    send_market_notification,
    settle_market_sale_proceeds,
)
from trade.services.market_rules import DEFAULT_TRADE_MARKET_RULES
from trade.services.market_rules import normalize_trade_market_rules as _normalize_trade_market_rules

if TYPE_CHECKING:
    from gameplay.models import ItemTemplate

logger = logging.getLogger(__name__)

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


# Dynamic facade assembly in market_facade.py resolves these names from this module at runtime.
_FACADE_EXPORTS = (
    timezone,
    LEGACY_TOOL_EFFECT_TYPES,
    _market_notification_helpers,
    _market_purchase_helpers,
    _expire_listings_queryset_impl,
    normalize_listing_inputs,
    create_listing_record,
    validate_gold_bar_availability,
    validate_listing_inventory,
    validate_listing_total_price,
    charge_listing_fee,
    decrement_market_listing_inventory,
    get_tradeable_inventory_queryset,
    grant_market_item_locked,
    load_market_item_template,
    lock_market_listing_inventory_item,
    pay_market_purchase,
    send_market_message,
    send_market_notification,
    settle_market_sale_proceeds,
)


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
    return _market_facade.create_listing_entry(
        manor,
        item_key,
        quantity,
        unit_price,
        duration,
        commands_module=_market_commands,
        service_module=sys.modules[__name__],
    )


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
    return _market_facade.get_active_listings_entry(
        item_template_id=item_template_id,
        order_by=order_by,
        category=category,
        rarity=rarity,
        queries_module=_market_queries,
        service_module=sys.modules[__name__],
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
    return _market_facade.purchase_listing_entry(
        buyer,
        listing_id,
        commands_module=_market_commands,
        service_module=sys.modules[__name__],
    )


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
    return _market_facade.cancel_listing_entry(
        manor,
        listing_id,
        commands_module=_market_commands,
        service_module=sys.modules[__name__],
    )


def _expire_listings_queryset(expired_listings: QuerySet, log_label: str, limit: int | None = None) -> int:
    return _market_facade.expire_listings_queryset_entrypoint(
        expired_listings,
        log_label,
        service_module=sys.modules[__name__],
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
    return _market_facade.expire_listings_entry(
        limit=limit,
        queries_module=_market_queries,
        service_module=sys.modules[__name__],
    )


def expire_user_listings(manor: Manor) -> int:
    """
    处理指定用户的过期挂单（用户访问交易行时主动触发）

    Args:
        manor: 庄园

    Returns:
        处理的挂单数量
    """
    return _market_facade.expire_user_listings_entry(
        manor,
        queries_module=_market_queries,
        service_module=sys.modules[__name__],
    )


def get_my_listings(manor: Manor, status: str = None) -> QuerySet:
    """
    获取我的挂单

    Args:
        manor: 庄园
        status: 状态筛选（可选）

    Returns:
        挂单查询集
    """
    return _market_facade.get_my_listings_entry(
        manor,
        status=status,
        queries_module=_market_queries,
        service_module=sys.modules[__name__],
    )


def get_market_stats() -> Dict:
    """
    获取交易行统计信息

    Returns:
        统计信息字典
    """
    return _market_facade.get_market_stats_entry(
        queries_module=_market_queries,
        service_module=sys.modules[__name__],
    )


def get_tradeable_inventory(manor: Manor) -> QuerySet:
    """
    获取可上架的物品列表

    IMPORTANT: Only show WAREHOUSE items since create_listing only operates on WAREHOUSE.

    Args:
        manor: 庄园

    Returns:
        可交易的库存物品查询集
    """
    return _market_facade.get_tradeable_inventory_entry(manor, service_module=sys.modules[__name__])
