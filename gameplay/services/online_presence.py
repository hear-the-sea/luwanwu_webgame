from __future__ import annotations

import logging
import time

from django.core.cache import cache

from core.utils.infrastructure import INFRASTRUCTURE_EXCEPTIONS
from gameplay.services.utils.cache_exceptions import CACHE_INFRASTRUCTURE_EXCEPTIONS

from .online_presence_backend import (
    ONLINE_USER_TOUCH_CACHE_KEY_PREFIX,
    ONLINE_USER_TOUCH_CACHE_TIMEOUT,
    ONLINE_USERS_CACHE_KEY,
    ONLINE_USERS_TTL_SECONDS,
    get_redis_connection_if_supported,
    touch_http_presence,
)

logger = logging.getLogger(__name__)


def _is_expected_cache_error(exc: Exception) -> bool:
    return isinstance(exc, CACHE_INFRASTRUCTURE_EXCEPTIONS)


def _safe_cache_add(key: str, value, timeout: int):
    try:
        return cache.add(key, value, timeout=timeout)
    except Exception as exc:
        if not _is_expected_cache_error(exc):
            raise
        logger.warning("Failed to add cache key: %s", key, exc_info=True)
        return None


def _safe_cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception as exc:
        if not _is_expected_cache_error(exc):
            raise
        logger.warning("Failed to delete cache key: %s", key, exc_info=True)


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
        touch_http_presence(redis, user_id=int(user_id), now_ts=now_ts, ttl_seconds=ONLINE_USERS_TTL_SECONDS)
        _safe_cache_delete(ONLINE_USERS_CACHE_KEY)
    except NotImplementedError:
        return
    except INFRASTRUCTURE_EXCEPTIONS:
        if should_refresh:
            _safe_cache_delete(touch_cache_key)
        logger.warning("Failed to refresh online user presence from HTTP request", exc_info=True)
    except Exception:
        if should_refresh:
            _safe_cache_delete(touch_cache_key)
        raise
