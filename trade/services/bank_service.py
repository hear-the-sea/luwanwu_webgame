"""
钱庄服务

动态汇率机制：
  实时汇率 = 基准价 × 总量系数 × 累进系数

  - 总量系数：基于活跃玩家的金条总量，金条越多价格越高（通胀控制）
  - 累进系数：基于当日个人已兑换数量，越买越贵（软限制）
"""

import logging
from typing import Any

from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from core.utils.cache_lock import release_cache_key_if_owner
from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from trade.models import GoldBarExchangeLog
from trade.services.trade_platform import spend_resources_locked

from . import rate_calculations as _rate_calculations

# Pure pricing constants and math functions extracted to bank_pricing.
from .bank_pricing import (  # noqa: F401
    ACTIVE_DAYS_THRESHOLD,
    DEGRADED_PRICING_SOURCES,
    GOLD_BAR_BASE_PRICE,
    GOLD_BAR_FEE_RATE,
    GOLD_BAR_ITEM_KEY,
    GOLD_BAR_MAX_PRICE,
    GOLD_BAR_MIN_PRICE,
    GOLD_BAR_PROGRESSIVE_FACTOR,
    GOLD_BAR_SUPPLY_FACTOR,
    GOLD_BAR_TARGET_SUPPLY,
    SUPPLY_CACHE_KEY,
    SUPPLY_CACHE_TTL,
    SUPPLY_STALE_CACHE_KEY,
    SUPPLY_STALE_CACHE_TTL,
    GoldBarPricingUnavailableError,
    _calculate_supply_factor_from_supply,
    _normalize_positive_quantity,
    _safe_int,
    calculate_progressive_factor,
)

logger = logging.getLogger(__name__)


BANK_INFRASTRUCTURE_EXCEPTIONS = (DatabaseError, ConnectionError, OSError, TimeoutError)


def _safe_cache_get(key: str, default: Any = None) -> Any:
    try:
        return cache.get(key, default)
    except Exception:
        logger.warning(
            "Failed to read cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )
        return default


def _safe_cache_set(key: str, value: Any, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning(
            "Failed to write cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )


def _safe_cache_add(key: str, value: Any, timeout: int) -> bool:
    try:
        return bool(cache.add(key, value, timeout=timeout))
    except Exception:
        logger.warning(
            "Failed to add cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )
        return False


def _safe_cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning(
            "Failed to delete cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )


def _strict_cache_get(key: str, default: Any = None) -> Any:
    try:
        return cache.get(key, default)
    except BANK_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.error(
            "Strict gold supply cache.get failed: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": "bank_cache"},
        )
        raise GoldBarPricingUnavailableError() from exc
    except Exception:
        logger.error(
            "Unexpected strict gold supply cache.get failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": "bank_cache"},
        )
        raise


def _strict_cache_add(key: str, value: Any, timeout: int) -> bool:
    try:
        return bool(cache.add(key, value, timeout=timeout))
    except BANK_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.error(
            "Strict gold supply cache.add failed: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": "bank_cache"},
        )
        raise GoldBarPricingUnavailableError() from exc
    except Exception:
        logger.error(
            "Unexpected strict gold supply cache.add failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": "bank_cache"},
        )
        raise


def _release_cache_lock_if_owner(lock_key: str, lock_token: str) -> None:
    """Best-effort lock release with ownership check."""
    released = release_cache_key_if_owner(
        lock_key,
        lock_token=lock_token,
        logger=logger,
        log_context="gold supply cache lock release",
    )
    if released:
        return

    # Fallback path for non-Redis cache backends or test monkeypatches.
    current_token = _safe_cache_get(lock_key)
    if current_token == lock_token:
        _safe_cache_delete(lock_key)


def get_today_exchange_count(manor: Manor) -> int:
    """获取今日已兑换金条数量"""
    # 安全修复：使用 timezone.now().date() 保持时区一致性
    today = timezone.now().date()
    count = GoldBarExchangeLog.objects.filter(manor=manor, exchange_date=today).aggregate(total=Sum("quantity"))[
        "total"
    ]
    return max(0, _safe_int(count, 0))


# ============ 动态汇率计算 ============
from .rate_calculations import (  # noqa: E402,F401
    _get_effective_gold_supply_data,
    _normalize_supply_value,
    calculate_dynamic_rate,
    calculate_gold_bar_cost,
    calculate_next_rate,
    calculate_supply_factor,
    get_effective_gold_supply,
)

_IMPORTED_GET_EFFECTIVE_GOLD_SUPPLY = get_effective_gold_supply
_IMPORTED_CALCULATE_SUPPLY_FACTOR = calculate_supply_factor

_rate_calculations.configure_bank_service_hooks(
    safe_cache_get=lambda key, default=None: _safe_cache_get(key, default),  # type: ignore[misc]
    safe_cache_set=lambda key, value, timeout: _safe_cache_set(key, value, timeout),
    safe_cache_add=lambda key, value, timeout: _safe_cache_add(key, value, timeout),
    safe_cache_delete=lambda key: _safe_cache_delete(key),
    release_cache_lock_if_owner=lambda lock_key, lock_token: _release_cache_lock_if_owner(lock_key, lock_token),
    get_today_exchange_count=lambda manor: get_today_exchange_count(manor),
    get_effective_gold_supply_override=lambda: (
        get_effective_gold_supply if get_effective_gold_supply is not _IMPORTED_GET_EFFECTIVE_GOLD_SUPPLY else None
    ),
    calculate_supply_factor_override=lambda: (
        calculate_supply_factor if calculate_supply_factor is not _IMPORTED_CALCULATE_SUPPLY_FACTOR else None
    ),
)


def exchange_gold_bar(manor: Manor, quantity: int) -> dict:
    """
    兑换金条（动态汇率版本）

    安全修复：
    - 将价格计算移入 transaction.atomic() 内部
    - 依托 Manor 行锁实现用户级串行化，防止并发低价买入漏洞

    Args:
        manor: 庄园对象
        quantity: 兑换数量

    Returns:
        dict: 兑换结果信息

    Raises:
        ValueError: 参数错误、银两不足等
    """
    quantity = _normalize_positive_quantity(quantity)

    # 检查金条物品模板是否存在
    try:
        gold_bar_template = ItemTemplate.objects.get(key=GOLD_BAR_ITEM_KEY)
    except ItemTemplate.DoesNotExist:
        raise ValueError("金条物品不存在，请联系管理员")

    # 执行兑换（并发安全版本）
    with transaction.atomic():
        manor_locked = Manor.objects.select_for_update().get(pk=manor.pk)

        # 安全修复：在锁内重新计算价格，确保基于最新的今日已兑换数量
        # 防止并发请求利用旧的低价买入
        cost_info = calculate_gold_bar_cost(manor_locked, quantity, fail_closed=True)
        total_cost = cost_info["total_cost"]

        try:
            spend_resources_locked(
                manor_locked,
                {"silver": total_cost},
                note=f"兑换金条 x{quantity}",
                reason=ResourceEvent.Reason.BANK_EXCHANGE,
            )
        except ValueError as exc:
            raise ValueError(
                f"银两不足，需要 {total_cost:,} 银两"
                f"（基础 {cost_info['base_cost']:,} + 手续费 {cost_info['fee']:,}）"
            ) from exc

        # 步骤2：锁定并增加金条库存
        # 锁定现有记录避免并发时数量增加被覆盖
        inventory_item = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=manor_locked,
                template=gold_bar_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )

        if inventory_item:
            # 已有金条，使用F()表达式增加数量
            InventoryItem.objects.filter(pk=inventory_item.pk).update(quantity=F("quantity") + quantity)
        else:
            # 首次获得金条，创建新记录
            InventoryItem.objects.create(
                manor=manor_locked,
                template=gold_bar_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity=quantity,
            )

        # 步骤3：记录兑换日志
        GoldBarExchangeLog.objects.create(manor=manor_locked, quantity=quantity, silver_cost=total_cost)

    # 清除供应量缓存，让下次查询获取最新数据
    _safe_cache_delete(SUPPLY_CACHE_KEY)

    return {
        "quantity": quantity,
        "total_cost": total_cost,
        "base_cost": cost_info["base_cost"],
        "fee": cost_info["fee"],
        "avg_rate": cost_info["avg_rate"],
        "rate_details": cost_info["rate_details"],
        "next_rate": calculate_next_rate(manor, fail_closed=True),
    }


def get_bank_info(manor: Manor) -> dict:
    """
    获取钱庄信息（动态汇率版本）

    Returns:
        dict: 包含动态汇率、手续费率、今日兑换情况等信息
    """
    effective_supply, pricing_source = _get_effective_gold_supply_data()
    pricing_degraded = pricing_source in DEGRADED_PRICING_SOURCES
    pricing_status_message = ""
    if pricing_source == "stale_cache":
        pricing_status_message = "钱庄汇率数据正在降级展示，当前价格可能不是最新值，已暂时关闭兑换。"
    elif pricing_source == "default":
        pricing_status_message = "钱庄汇率数据暂时不可用，已暂时关闭兑换。"

    today_count = get_today_exchange_count(manor)
    supply_factor = _calculate_supply_factor_from_supply(effective_supply)
    current_rate = calculate_dynamic_rate(manor, supply_factor=supply_factor)
    next_rate = calculate_next_rate(manor, supply_factor=supply_factor)
    progressive_factor = calculate_progressive_factor(today_count)

    # 计算单根金条的总费用（含手续费）
    cost_info = calculate_gold_bar_cost(manor, 1, supply_factor=supply_factor)

    return {
        # 基础配置
        "gold_bar_base_price": GOLD_BAR_BASE_PRICE,
        "gold_bar_fee_rate": float(GOLD_BAR_FEE_RATE) * 100,  # 转换为百分比
        "gold_bar_min_price": GOLD_BAR_MIN_PRICE,
        "gold_bar_max_price": GOLD_BAR_MAX_PRICE,
        # 动态汇率信息
        "current_rate": current_rate,
        "next_rate": next_rate,
        "total_cost_per_bar": cost_info["total_cost"],
        "supply_factor": round(supply_factor, 3),
        "progressive_factor": round(progressive_factor, 3),
        "effective_supply": effective_supply,
        "pricing_source": pricing_source,
        "pricing_degraded": pricing_degraded,
        "pricing_status_message": pricing_status_message,
        "exchange_available": not pricing_degraded,
        # 个人兑换情况
        "today_count": today_count,
        "manor_silver": manor.silver,
    }
