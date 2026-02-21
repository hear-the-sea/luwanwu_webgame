from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from django_redis import get_redis_connection

from .services import unread_message_count

logger = logging.getLogger(__name__)

User = get_user_model()


def _safe_cache_get(key: str, default=None):
    try:
        return cache.get(key, default)
    except Exception:
        logger.warning("Failed to read cache key: %s", key, exc_info=True)
        return default


def _safe_cache_set(key: str, value, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("Failed to write cache key: %s", key, exc_info=True)


def _safe_int(value, default: int = 0) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, resolved)


def notifications(request):
    """
    Provide unread message count and user statistics to every template.

    The notification badge in the navigation bar depends on this context value.
    Also provides online_user_count and total_user_count (excluding staff/superusers).

    Performance optimizations:
    - User counts are cached for 5 minutes
    - Online count uses Redis atomic SET operations
    - Sidebar raid/scout data cached for 10 seconds per user
    - Player rank cached for 30 seconds per user
    """
    context = {"message_unread_count": 0, "online_user_count": 0, "total_user_count": 0}

    # 计算真实用户统计（排除管理员） - 使用缓存避免每次请求查询
    cache_key_total = "stats:total_users_count"
    total_count = _safe_cache_get(cache_key_total)
    if total_count is None:
        total_count = User.objects.filter(is_staff=False, is_superuser=False).count()
        _safe_cache_set(cache_key_total, total_count, timeout=300)  # 5分钟缓存
    context["total_user_count"] = _safe_int(total_count)

    # 在线用户统计 - 使用短时缓存 + Redis SET（与WebSocket consumer一致）
    # 性能优化：添加5秒缓存减少Redis读取频率，并优化Redis异常时的降级策略
    cache_key_online = "stats:online_users_count"
    cached_online = _safe_cache_get(cache_key_online)

    if cached_online is not None:
        # Cache hit - 直接使用缓存值
        context["online_user_count"] = _safe_int(cached_online)
    else:
        # Cache miss - 从Redis读取
        try:
            redis = get_redis_connection("default")
            # 与 OnlineStatsConsumer 保持一致：使用 ZSET + last-seen 时间戳（epoch seconds）
            online_users_key = "online_users_zset"
            online_users_ttl = 1800  # 30 minutes
            cutoff = float(time.time()) - float(online_users_ttl)
            # best-effort cleanup，避免过期用户导致计数漂移
            redis.zremrangebyscore(online_users_key, "-inf", cutoff)
            online_count = int(redis.zcard(online_users_key) or 0)
            # 缓存5秒以减少高频请求时的Redis读取
            _safe_cache_set(cache_key_online, online_count, timeout=5)
            context["online_user_count"] = online_count
        except Exception:
            # Redis异常时的多层降级策略
            # 1. 尝试使用之前的缓存值（可能已过期但仍可用）
            fallback_cached = _safe_cache_get(cache_key_online)
            if fallback_cached is not None:
                context["online_user_count"] = _safe_int(fallback_cached)
            else:
                # 2. 最后手段：查询数据库（仅在完全无缓存时）
                time_threshold = timezone.now() - timedelta(minutes=30)
                online_count = User.objects.filter(
                    is_staff=False,
                    is_superuser=False,
                    last_login__gte=time_threshold
                ).count()
                context["online_user_count"] = online_count
                # 缓存1分钟，避免Redis宕机期间频繁查询数据库
                _safe_cache_set(cache_key_online, online_count, timeout=60)

    if not request.user.is_authenticated:
        return context

    try:
        manor = request.user.manor
        manor_id = manor.id
        context["message_unread_count"] = unread_message_count(manor)

        # 声望和排名数据 - 排名查询使用30秒缓存
        from .services.ranking import get_player_rank
        context["sidebar_prestige"] = manor.prestige

        cache_key_rank = f"sidebar:rank:{manor_id}"
        cached_rank = _safe_cache_get(cache_key_rank)
        if cached_rank is not None:
            context["sidebar_rank"] = cached_rank
        else:
            rank = get_player_rank(manor)
            _safe_cache_set(cache_key_rank, rank, timeout=30)
            context["sidebar_rank"] = rank

        # 侦察和出征状态数据 - 使用10秒缓存减少数据库查询
        from .services.raid import (
            get_active_raids,
            get_active_scouts,
            get_incoming_raids,
        )

        cache_key_raids = f"sidebar:raids:{manor_id}"
        cached_raids = _safe_cache_get(cache_key_raids)
        if isinstance(cached_raids, dict) and {"active", "scouts", "incoming"}.issubset(cached_raids.keys()):
            context["sidebar_active_raids"] = cached_raids["active"]
            context["sidebar_active_scouts"] = cached_raids["scouts"]
            context["sidebar_incoming_raids"] = cached_raids["incoming"]
        else:
            active_raids = get_active_raids(manor)
            active_scouts = get_active_scouts(manor)
            incoming_raids = get_incoming_raids(manor)
            _safe_cache_set(
                cache_key_raids,
                {
                    "active": active_raids,
                    "scouts": active_scouts,
                    "incoming": incoming_raids,
                },
                timeout=10,
            )
            context["sidebar_active_raids"] = active_raids
            context["sidebar_active_scouts"] = active_scouts
            context["sidebar_incoming_raids"] = incoming_raids
    except Exception:
        # 代码质量修复：记录异常以便排查问题，而非静默忽略
        logger.warning("Failed to load sidebar context", exc_info=True)

    return context
