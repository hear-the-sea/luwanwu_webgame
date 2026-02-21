"""
缓存管理服务

提供统一的缓存key管理和缓存操作。
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar, cast

from django.core.cache import cache

# 缓存超时时间常量（秒）
CACHE_TIMEOUT_SHORT = 5  # 5秒 - 实时性要求高的数据
CACHE_TIMEOUT_MEDIUM = 30  # 30秒 - 中等实时性要求
CACHE_TIMEOUT_LONG = 60  # 60秒 - 低实时性要求
CACHE_TIMEOUT_RANKING = 60  # 排行榜缓存
CACHE_TIMEOUT_CONFIG = 300  # 5分钟 - 配置类数据


class CacheKeys:
    """缓存键前缀和生成器"""

    # 排行榜相关
    RANKING_PRESTIGE = "ranking:prestige"
    RANKING_TOTAL_PLAYERS = "ranking:total_players"
    PLAYER_RANK_PREFIX = "player_rank"

    # 消息相关
    UNREAD_COUNT_PREFIX = "unread_count:manor"

    # 庄园状态
    MANOR_STATS_PREFIX = "manor_stats"

    # 科技加成
    TECH_BONUS_PREFIX = "tech_bonus"
    HOME_HOURLY_RATES_PREFIX = "manor_home_hourly_rates"

    # 门客模板相关
    GUEST_TEMPLATES_BY_RARITY = "guest_templates:by_rarity"
    HERMIT_TEMPLATES = "guest_templates:hermit"

    @staticmethod
    def player_rank(manor_id: int, prestige: int) -> str:
        """玩家排名缓存键"""
        return f"{CacheKeys.PLAYER_RANK_PREFIX}:{manor_id}:{prestige}"

    @staticmethod
    def unread_count(manor_id: int) -> str:
        """未读消息数缓存键"""
        return f"{CacheKeys.UNREAD_COUNT_PREFIX}:{manor_id}"

    @staticmethod
    def manor_stats(manor_id: int) -> str:
        """庄园统计数据缓存键"""
        return f"{CacheKeys.MANOR_STATS_PREFIX}:{manor_id}"

    @staticmethod
    def tech_bonus(manor_id: int, tech_key: str) -> str:
        """科技加成缓存键"""
        return f"{CacheKeys.TECH_BONUS_PREFIX}:{manor_id}:{tech_key}"

    @staticmethod
    def home_hourly_rates(manor_id: int) -> str:
        """首页建筑产出缓存键"""
        return f"{CacheKeys.HOME_HOURLY_RATES_PREFIX}:{manor_id}"


def invalidate_home_stats_cache(manor_id: int) -> None:
    """清除首页统计类缓存。"""
    cache.delete(CacheKeys.home_hourly_rates(manor_id))


def invalidate_manor_cache(manor_id: int) -> None:
    """
    清除庄园相关的所有缓存。

    在庄园数据发生变化时调用。

    Args:
        manor_id: 庄园ID
    """
    keys_to_delete = [
        CacheKeys.unread_count(manor_id),
        CacheKeys.manor_stats(manor_id),
    ]
    cache.delete_many(keys_to_delete)


def invalidate_ranking_cache() -> None:
    """
    清除排行榜缓存。

    在声望发生变化时调用。
    """
    cache.delete(CacheKeys.RANKING_PRESTIGE)
    cache.delete(CacheKeys.RANKING_TOTAL_PLAYERS)


T = TypeVar("T")


def cached(
    key_func: Callable[..., str],
    timeout: int = CACHE_TIMEOUT_MEDIUM,
    cache_none: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    缓存装饰器。

    Args:
        key_func: 生成缓存键的函数，接收与被装饰函数相同的参数
        timeout: 缓存超时时间（秒）
        cache_none: 是否缓存None值

    Returns:
        装饰器函数

    Example:
        @cached(lambda manor: f"manor_data:{manor.id}", timeout=60)
        def get_manor_data(manor):
            return expensive_computation(manor)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            cache_key = key_func(*args, **kwargs)
            sentinel = object()
            result = cache.get(cache_key, sentinel)

            if result is not sentinel:
                # If `cache_none=False` we don't normally store None, but keep
                # compatibility with legacy callers that may have cached None.
                if result is None and not cache_none:
                    return cast(T, None)
                return cast(T, result)

            computed = func(*args, **kwargs)
            if computed is not None or cache_none:
                cache.set(cache_key, computed, timeout=timeout)
            return cast(T, computed)

        return wrapper

    return decorator


def get_or_set(
    key: str,
    default_func: Callable[[], T],
    timeout: int = CACHE_TIMEOUT_MEDIUM
) -> T:
    """
    获取缓存值，如果不存在则计算并设置。

    Args:
        key: 缓存键
        default_func: 计算默认值的函数
        timeout: 缓存超时时间

    Returns:
        缓存值或计算的默认值
    """
    result = cache.get(key)
    if result is None:
        result = default_func()
        cache.set(key, result, timeout=timeout)
    return cast(T, result)
