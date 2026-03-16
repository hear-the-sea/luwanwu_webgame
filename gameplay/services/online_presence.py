from __future__ import annotations

import logging
import time

from django.core.cache import cache
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

ONLINE_USERS_ZSET_KEY = "online_users_zset"
ONLINE_USERS_TTL_SECONDS = 1800
ONLINE_USER_TOUCH_CACHE_KEY_PREFIX = "stats:online_users:touch:"
ONLINE_USER_TOUCH_CACHE_TIMEOUT = 60
ONLINE_USERS_CACHE_KEY = "stats:online_users_count"


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


def get_redis_connection_if_supported():
    try:
        return get_redis_connection("default")
    except NotImplementedError:
        return None


def refresh_online_presence_from_request(user) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return

    user_id = getattr(user, "id", None)
    if not user_id:
        return

    username = str(getattr(user, "username", "") or "").strip()
    touch_cache_key = f"{ONLINE_USER_TOUCH_CACHE_KEY_PREFIX}{int(user_id)}:{username}"
    should_refresh = _safe_cache_add(touch_cache_key, 1, timeout=ONLINE_USER_TOUCH_CACHE_TIMEOUT)
    if should_refresh is False:
        return

    try:
        redis = get_redis_connection_if_supported()
        if redis is None:
            return
        now_ts = float(time.time())
        redis.zadd(ONLINE_USERS_ZSET_KEY, {int(user_id): now_ts})
        redis.expire(ONLINE_USERS_ZSET_KEY, ONLINE_USERS_TTL_SECONDS * 2)
        _safe_cache_delete(ONLINE_USERS_CACHE_KEY)
    except NotImplementedError:
        return
    except Exception:
        if should_refresh:
            _safe_cache_delete(touch_cache_key)
        logger.warning("Failed to refresh online user presence from HTTP request", exc_info=True)
