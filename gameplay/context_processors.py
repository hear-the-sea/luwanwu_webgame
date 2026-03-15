from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.utils import timezone
from django_redis import get_redis_connection

from gameplay.services.utils.messages import unread_message_count

logger = logging.getLogger(__name__)

User = get_user_model()

TOTAL_USERS_CACHE_KEY = "stats:total_users_count"
ONLINE_USERS_CACHE_KEY = "stats:online_users_count"
ONLINE_USERS_ZSET_KEY = "online_users_zset"
TOTAL_USERS_CACHE_TIMEOUT = 300
ONLINE_USERS_CACHE_TIMEOUT = 5
ONLINE_USERS_FALLBACK_CACHE_TIMEOUT = 60
ONLINE_USERS_TTL_SECONDS = 1800
ONLINE_USER_TOUCH_CACHE_KEY_PREFIX = "stats:online_users:touch:"
ONLINE_USER_TOUCH_CACHE_TIMEOUT = 60
SIDEBAR_RANK_CACHE_TIMEOUT = 30
DEFAULT_PROTECTION_STATUS = {"is_protected": False, "type_display": "", "remaining_display": ""}


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


def _safe_cache_add(key: str, value, timeout: int):
    try:
        return cache.add(key, value, timeout=timeout)
    except Exception:
        logger.warning("Failed to add cache key: %s", key, exc_info=True)
        return None


def _safe_cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning("Failed to delete cache key: %s", key, exc_info=True)


def _safe_int(value, default: int = 0) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, resolved)


def _build_default_context() -> dict[str, Any]:
    return {
        "message_unread_count": 0,
        "online_user_count": 0,
        "total_user_count": 0,
        "header_protection_status": DEFAULT_PROTECTION_STATUS.copy(),
    }


def _load_total_user_count() -> int:
    total_count = _safe_cache_get(TOTAL_USERS_CACHE_KEY)
    if total_count is None:
        total_count = User.objects.filter(is_staff=False, is_superuser=False).count()
        _safe_cache_set(TOTAL_USERS_CACHE_KEY, total_count, timeout=TOTAL_USERS_CACHE_TIMEOUT)
    return _safe_int(total_count)


def _load_online_user_count_from_redis() -> int:
    redis = get_redis_connection("default")
    cutoff = float(time.time()) - float(ONLINE_USERS_TTL_SECONDS)
    redis.zremrangebyscore(ONLINE_USERS_ZSET_KEY, "-inf", cutoff)
    return _safe_int(redis.zcard(ONLINE_USERS_ZSET_KEY))


def _load_online_user_count_from_db() -> int:
    time_threshold = timezone.now() - timedelta(minutes=30)
    return User.objects.filter(is_staff=False, is_superuser=False, last_login__gte=time_threshold).count()


def _load_online_user_count() -> int:
    cached_online = _safe_cache_get(ONLINE_USERS_CACHE_KEY)
    if cached_online is not None:
        return _safe_int(cached_online)

    try:
        online_count = _load_online_user_count_from_redis()
    except Exception:
        logger.warning("Failed to load online user count from Redis", exc_info=True)
        fallback_cached = _safe_cache_get(ONLINE_USERS_CACHE_KEY)
        if fallback_cached is not None:
            return _safe_int(fallback_cached)
        online_count = _load_online_user_count_from_db()
        _safe_cache_set(ONLINE_USERS_CACHE_KEY, online_count, timeout=ONLINE_USERS_FALLBACK_CACHE_TIMEOUT)
        return online_count

    _safe_cache_set(ONLINE_USERS_CACHE_KEY, online_count, timeout=ONLINE_USERS_CACHE_TIMEOUT)
    return online_count


def refresh_online_presence_from_request(user) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return

    user_id = getattr(user, "id", None)
    if not user_id:
        return

    touch_cache_key = f"{ONLINE_USER_TOUCH_CACHE_KEY_PREFIX}{int(user_id)}"
    should_refresh = _safe_cache_add(touch_cache_key, 1, timeout=ONLINE_USER_TOUCH_CACHE_TIMEOUT)
    if should_refresh is False:
        return

    try:
        redis = get_redis_connection("default")
        now_ts = float(time.time())
        redis.zadd(ONLINE_USERS_ZSET_KEY, {int(user_id): now_ts})
        redis.expire(ONLINE_USERS_ZSET_KEY, ONLINE_USERS_TTL_SECONDS * 2)
        _safe_cache_delete(ONLINE_USERS_CACHE_KEY)
    except Exception:
        if should_refresh:
            _safe_cache_delete(touch_cache_key)
        logger.warning("Failed to refresh online user presence from HTTP request", exc_info=True)


def _load_sidebar_rank(manor) -> int:
    from gameplay.services.ranking import get_player_rank

    cache_key_rank = f"sidebar:rank:{manor.id}"
    cached_rank = _safe_cache_get(cache_key_rank)
    if cached_rank is not None:
        return _safe_int(cached_rank)

    rank = _safe_int(get_player_rank(manor))
    _safe_cache_set(cache_key_rank, rank, timeout=SIDEBAR_RANK_CACHE_TIMEOUT)
    return rank


def _should_include_home_sidebar(request) -> bool:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is not None and getattr(resolver_match, "url_name", None) == "home":
        return True
    return getattr(request, "path", "") == "/"


def _populate_authenticated_context(context: dict[str, Any], request) -> None:
    try:
        manor = request.user.manor
    except (ObjectDoesNotExist, DatabaseError):
        logger.warning("Failed to resolve manor for sidebar context", exc_info=True)
        return

    try:
        context["message_unread_count"] = unread_message_count(manor)
    except DatabaseError:
        logger.warning("Failed to load unread message count", exc_info=True)

    try:
        from gameplay.services.raid import get_protection_status

        protection_status = get_protection_status(manor)
        if isinstance(protection_status, dict):
            context["header_protection_status"] = protection_status
    except DatabaseError:
        logger.warning("Failed to load protection status", exc_info=True)

    if not _should_include_home_sidebar(request):
        return

    context["sidebar_prestige"] = manor.prestige

    try:
        context["sidebar_rank"] = _load_sidebar_rank(manor)
    except DatabaseError:
        logger.warning("Failed to load sidebar rank", exc_info=True)


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
    context = _build_default_context()
    context["total_user_count"] = _load_total_user_count()

    context["online_user_count"] = _load_online_user_count()

    if not request.user.is_authenticated:
        return context

    _populate_authenticated_context(context, request)
    return context
