"""
钱庄利率计算

从 bank_service 中提取的汇率相关读逻辑与费用计算。
本模块不依赖 exchange 交易流程，可被 bank_service 重新导出。
"""

import logging
import uuid
from datetime import timedelta
from typing import Any, Callable

from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Sum
from django.utils import timezone

from core.utils.cache_lock import release_cache_key_if_owner
from gameplay.models import InventoryItem, Manor
from trade.models import GoldBarExchangeLog

from .bank_pricing import (
    ACTIVE_DAYS_THRESHOLD,
    GOLD_BAR_BASE_PRICE,
    GOLD_BAR_FEE_RATE,
    GOLD_BAR_ITEM_KEY,
    GOLD_BAR_MAX_PRICE,
    GOLD_BAR_MIN_PRICE,
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

_safe_cache_get_hook: Callable[[str, Any], Any] | None = None
_safe_cache_set_hook: Callable[[str, Any, int], None] | None = None
_safe_cache_add_hook: Callable[[str, Any, int], bool] | None = None
_safe_cache_delete_hook: Callable[[str], None] | None = None
_release_cache_lock_if_owner_hook: Callable[[str, str], None] | None = None
_get_today_exchange_count_hook: Callable[[Manor], int] | None = None
_get_effective_gold_supply_override_hook: Callable[[], Callable[..., int] | None] | None = None
_calculate_supply_factor_override_hook: Callable[[], Callable[..., float] | None] | None = None


def configure_bank_service_hooks(
    *,
    safe_cache_get: Callable[[str, Any], Any] | None = None,
    safe_cache_set: Callable[[str, Any, int], None] | None = None,
    safe_cache_add: Callable[[str, Any, int], bool] | None = None,
    safe_cache_delete: Callable[[str], None] | None = None,
    release_cache_lock_if_owner: Callable[[str, str], None] | None = None,
    get_today_exchange_count: Callable[[Manor], int] | None = None,
    get_effective_gold_supply_override: Callable[[], Callable[..., int] | None] | None = None,
    calculate_supply_factor_override: Callable[[], Callable[..., float] | None] | None = None,
) -> None:
    global _safe_cache_get_hook
    global _safe_cache_set_hook
    global _safe_cache_add_hook
    global _safe_cache_delete_hook
    global _release_cache_lock_if_owner_hook
    global _get_today_exchange_count_hook
    global _get_effective_gold_supply_override_hook
    global _calculate_supply_factor_override_hook

    _safe_cache_get_hook = safe_cache_get
    _safe_cache_set_hook = safe_cache_set
    _safe_cache_add_hook = safe_cache_add
    _safe_cache_delete_hook = safe_cache_delete
    _release_cache_lock_if_owner_hook = release_cache_lock_if_owner
    _get_today_exchange_count_hook = get_today_exchange_count
    _get_effective_gold_supply_override_hook = get_effective_gold_supply_override
    _calculate_supply_factor_override_hook = calculate_supply_factor_override


def _default_safe_cache_get(key: str, default: Any = None) -> Any:
    try:
        return cache.get(key, default)
    except Exception:
        logger.warning(
            "Failed to read cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )
        return default


def _default_safe_cache_set(key: str, value: Any, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning(
            "Failed to write cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )


def _default_safe_cache_add(key: str, value: Any, timeout: int) -> bool:
    try:
        return bool(cache.add(key, value, timeout=timeout))
    except Exception:
        logger.warning(
            "Failed to add cache key: %s", key, exc_info=True, extra={"degraded": True, "component": "bank_cache"}
        )
        return False


def _default_safe_cache_delete(key: str) -> None:
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


def _call_safe_cache_get(key: str, default: Any = None) -> Any:
    if _safe_cache_get_hook is not None:
        return _safe_cache_get_hook(key, default)
    return _default_safe_cache_get(key, default)


def _call_safe_cache_set(key: str, value: Any, timeout: int) -> None:
    if _safe_cache_set_hook is not None:
        _safe_cache_set_hook(key, value, timeout)
        return
    _default_safe_cache_set(key, value, timeout)


def _call_safe_cache_add(key: str, value: Any, timeout: int) -> bool:
    if _safe_cache_add_hook is not None:
        return _safe_cache_add_hook(key, value, timeout)
    return _default_safe_cache_add(key, value, timeout)


def _call_safe_cache_delete(key: str) -> None:
    if _safe_cache_delete_hook is not None:
        _safe_cache_delete_hook(key)
        return
    _default_safe_cache_delete(key)


def _call_release_cache_lock_if_owner(lock_key: str, lock_token: str) -> None:
    if _release_cache_lock_if_owner_hook is not None:
        _release_cache_lock_if_owner_hook(lock_key, lock_token)
        return

    released = release_cache_key_if_owner(
        lock_key,
        lock_token=lock_token,
        logger=logger,
        log_context="gold supply cache lock release",
    )
    if released:
        return

    current_token = _call_safe_cache_get(lock_key)
    if current_token == lock_token:
        _call_safe_cache_delete(lock_key)


def _get_today_exchange_count_value(manor: Manor) -> int:
    if _get_today_exchange_count_hook is not None:
        return _get_today_exchange_count_hook(manor)

    today = timezone.now().date()
    count = GoldBarExchangeLog.objects.filter(manor=manor, exchange_date=today).aggregate(total=Sum("quantity"))[
        "total"
    ]
    return max(0, _safe_int(count, 0))


def _resolve_get_effective_gold_supply() -> Callable[..., int]:
    if _get_effective_gold_supply_override_hook is not None:
        override = _get_effective_gold_supply_override_hook()
        if override is not None:
            return override
    return get_effective_gold_supply


def _resolve_calculate_supply_factor() -> Callable[..., float]:
    if _calculate_supply_factor_override_hook is not None:
        override = _calculate_supply_factor_override_hook()
        if override is not None:
            return override
    return calculate_supply_factor


def _normalize_supply_value(raw_value: Any, *, source: str, fail_closed: bool) -> int:
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError) as exc:
        logger.warning("Invalid gold supply value from %s: %r", source, raw_value, exc_info=True)
        if fail_closed:
            raise GoldBarPricingUnavailableError() from exc
        return GOLD_BAR_TARGET_SUPPLY


def _get_effective_gold_supply_data(*, fail_closed: bool = False) -> tuple[int, str]:
    """
    获取有效金条供应量（仅统计活跃玩家）

    只统计最近 ACTIVE_DAYS_THRESHOLD 天内有登录的玩家持有的金条，
    排除弃游玩家的"死金条"对汇率的影响。

    缓存策略（三级降级）：
    1. 主缓存有效 → 直接返回
    2. 主缓存失效 + 获取锁成功 → 查询数据库并更新缓存
    3. 主缓存失效 + 获取锁失败 → 使用过期缓存（stale cache）
    4. 过期缓存也没有 → 返回默认值

    Returns:
        tuple[int, str]: (活跃玩家持有的金条总量, 数据来源)
    """
    cache_get = _strict_cache_get if fail_closed else _call_safe_cache_get
    cache_add = _strict_cache_add if fail_closed else _call_safe_cache_add

    cached = cache_get(SUPPLY_CACHE_KEY)
    if cached is not None:
        return _normalize_supply_value(cached, source="cache", fail_closed=fail_closed), "cache"

    lock_key = f"{SUPPLY_CACHE_KEY}:lock"
    lock_token = uuid.uuid4().hex
    lock_acquired = cache_add(lock_key, lock_token, timeout=10)

    if not lock_acquired:
        stale = cache_get(SUPPLY_STALE_CACHE_KEY)
        if stale is not None:
            stale_value = _normalize_supply_value(stale, source="stale_cache", fail_closed=fail_closed)
            if fail_closed:
                logger.error("Gold supply strict path rejected stale cache pricing")
                raise GoldBarPricingUnavailableError()
            logger.info("Gold supply cache miss, using stale cache value: %d", stale_value)
            return stale_value, "stale_cache"
        if fail_closed:
            logger.error("Gold supply strict path rejected default pricing fallback")
            raise GoldBarPricingUnavailableError()
        logger.warning("Gold supply cache miss and no stale cache, using default")
        return GOLD_BAR_TARGET_SUPPLY, "default"

    try:
        cutoff = timezone.now() - timedelta(days=ACTIVE_DAYS_THRESHOLD)

        result = InventoryItem.objects.filter(
            template__key=GOLD_BAR_ITEM_KEY,
            manor__user__last_login__gte=cutoff,
        ).aggregate(total=Sum("quantity"))

        total = max(0, _safe_int(result["total"], 0))
        _call_safe_cache_set(SUPPLY_CACHE_KEY, total, SUPPLY_CACHE_TTL)
        _call_safe_cache_set(SUPPLY_STALE_CACHE_KEY, total, SUPPLY_STALE_CACHE_TTL)
        return total, "db"
    except BANK_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.warning(
            "Failed to query gold supply: %s",
            exc,
            exc_info=True,
            extra={"degraded": True, "component": "bank_gold_supply"},
        )
        if fail_closed:
            raise GoldBarPricingUnavailableError() from exc
        stale = _call_safe_cache_get(SUPPLY_STALE_CACHE_KEY)
        if stale is not None:
            return _normalize_supply_value(stale, source="stale_cache", fail_closed=False), "stale_cache"
        return GOLD_BAR_TARGET_SUPPLY, "default"
    except Exception:
        logger.error(
            "Unexpected gold supply query failure",
            exc_info=True,
            extra={"degraded": True, "component": "bank_gold_supply"},
        )
        raise
    finally:
        _call_release_cache_lock_if_owner(lock_key, lock_token)


def get_effective_gold_supply(*, fail_closed: bool = False) -> int:
    return _get_effective_gold_supply_data(fail_closed=fail_closed)[0]


def calculate_supply_factor(*, fail_closed: bool = False) -> float:
    """
    计算总量系数

    基于活跃玩家的金条总量，使用对数函数平滑调节：
    - 金条总量 < 基准量：系数 < 1（价格降低，鼓励兑换）
    - 金条总量 > 基准量：系数 > 1（价格上涨，抑制兑换）

    Returns:
        float: 总量系数，范围 0.85 ~ 1.40
    """
    get_supply = _resolve_get_effective_gold_supply()
    total_supply = get_supply(fail_closed=fail_closed) if fail_closed else get_supply()
    return _calculate_supply_factor_from_supply(total_supply)


def calculate_dynamic_rate(manor: Manor, *, supply_factor: float | None = None, fail_closed: bool = False) -> int:
    """
    计算当前动态汇率

    公式：实时汇率 = 基准价 × 总量系数 × 累进系数

    Args:
        manor: 庄园对象

    Returns:
        int: 当前汇率（银两/金条）
    """
    if supply_factor is None:
        supply_factor_fn = _resolve_calculate_supply_factor()
        supply_factor = supply_factor_fn(fail_closed=fail_closed) if fail_closed else supply_factor_fn()
    today_count = _get_today_exchange_count_value(manor)
    progressive_factor = calculate_progressive_factor(today_count)

    rate = int(GOLD_BAR_BASE_PRICE * supply_factor * progressive_factor)
    return max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, rate))


def calculate_next_rate(manor: Manor, *, supply_factor: float | None = None, fail_closed: bool = False) -> int:
    """
    计算下一根金条的汇率（用于显示）

    Args:
        manor: 庄园对象

    Returns:
        int: 下一根金条的汇率
    """
    if supply_factor is None:
        supply_factor_fn = _resolve_calculate_supply_factor()
        supply_factor = supply_factor_fn(fail_closed=fail_closed) if fail_closed else supply_factor_fn()
    today_count = _get_today_exchange_count_value(manor)
    progressive_factor = calculate_progressive_factor(today_count + 1)

    rate = int(GOLD_BAR_BASE_PRICE * supply_factor * progressive_factor)
    return max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, rate))


def calculate_gold_bar_cost(
    manor: Manor,
    quantity: int,
    *,
    supply_factor: float | None = None,
    fail_closed: bool = False,
) -> dict:
    """
    计算兑换金条所需银两（含手续费）

    优化：
    - 修复了 O(N) 性能问题，针对累进系数封顶（12根）后的计算进行数学优化
    - 即使购买 10000 根也能瞬间完成计算

    Args:
        manor: 庄园对象
        quantity: 兑换数量

    Returns:
        dict: 包含各项费用明细
    """
    quantity = _normalize_positive_quantity(quantity)
    if supply_factor is None:
        supply_factor_fn = _resolve_calculate_supply_factor()
        supply_factor = supply_factor_fn(fail_closed=fail_closed) if fail_closed else supply_factor_fn()
    today_count = max(0, _safe_int(_get_today_exchange_count_value(manor), 0))

    base_cost = 0
    rate_details: list[int] = []

    calculated_count = 0
    current_idx = 0

    while calculated_count < quantity:
        current_count = today_count + current_idx
        if current_count >= 12:
            break

        progressive_factor = calculate_progressive_factor(current_count)
        rate = int(GOLD_BAR_BASE_PRICE * supply_factor * progressive_factor)
        rate = max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, rate))

        base_cost += rate
        if len(rate_details) < 10:
            rate_details.append(rate)

        calculated_count += 1
        current_idx += 1

    remaining = quantity - calculated_count
    if remaining > 0:
        capped_factor = 1.60
        capped_rate = int(GOLD_BAR_BASE_PRICE * supply_factor * capped_factor)
        capped_rate = max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, capped_rate))

        base_cost += capped_rate * remaining

        if len(rate_details) < 10:
            rate_details.append(capped_rate)

    fee = int(base_cost * GOLD_BAR_FEE_RATE)
    total_cost = base_cost + fee

    return {
        "base_cost": base_cost,
        "fee": fee,
        "total_cost": total_cost,
        "rate_details": rate_details,
        "avg_rate": base_cost // quantity if quantity > 0 else 0,
    }
