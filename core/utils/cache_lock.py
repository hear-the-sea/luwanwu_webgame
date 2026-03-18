from __future__ import annotations

import logging
import time
import uuid
from threading import Lock

from django.conf import settings
from django.core.cache import cache

_LOCAL_LOCKS: dict[str, tuple[str, float]] = {}
_LOCAL_LOCKS_GUARD = Lock()
_LOCAL_LOCKS_MAX_SIZE = 20000
_LOCAL_LOCK_KEY_PREFIX = "local:"
_CACHE_RELEASE_IF_OWNER_SCRIPT = """
local lock_key = KEYS[1]
local expected_token = ARGV[1]
local current_token = redis.call('GET', lock_key)
if not current_token then
  return 0
end
if current_token == expected_token then
  return redis.call('DEL', lock_key)
end
return 0
"""


def _cleanup_expired_local_locks(now: float) -> None:
    expired_keys = [key for key, (_token, expires_at) in _LOCAL_LOCKS.items() if expires_at <= now]
    for key in expired_keys:
        _LOCAL_LOCKS.pop(key, None)


def _make_lock_token() -> str:
    return uuid.uuid4().hex


def _release_cache_lock_atomic_if_owner(
    key: str,
    *,
    lock_token: str,
    logger: logging.Logger,
    log_context: str,
) -> bool | None:
    """
    Try atomic compare-and-delete in Redis.

    Returns:
        True: deleted successfully
        False: key missing / ownership mismatch
        None: atomic release unavailable; caller may fallback
    """
    try:
        from django_redis import get_redis_connection
    except Exception:
        return None

    try:
        redis = get_redis_connection("default")
    except NotImplementedError:
        return None
    except Exception as exc:
        logger.warning(
            "%s atomic cache lock release unavailable, fallback to compare-delete: key=%s error=%s",
            log_context,
            key,
            exc,
            exc_info=True,
        )
        return None

    try:
        redis_key = cache.make_key(key) if hasattr(cache, "make_key") else key  # type: ignore[attr-defined]
        deleted = redis.eval(_CACHE_RELEASE_IF_OWNER_SCRIPT, 1, redis_key, lock_token)
        return bool(int(deleted or 0))
    except Exception as exc:
        logger.warning(
            "%s atomic cache lock release unavailable, fallback to compare-delete: key=%s error=%s",
            log_context,
            key,
            exc,
            exc_info=True,
        )
        return None


def _release_cache_lock_non_atomic_if_owner(
    key: str,
    *,
    lock_token: str,
    logger: logging.Logger,
    log_context: str,
) -> bool:
    """Best-effort compare-delete fallback for non-Redis caches."""
    try:
        current_token = cache.get(key)
    except Exception as exc:
        logger.warning(
            "%s cache lock ownership check failed: key=%s error=%s",
            log_context,
            key,
            exc,
            exc_info=True,
        )
        return False

    if current_token != lock_token:
        return False

    try:
        cache.delete(key)
        return True
    except Exception as exc:
        logger.warning(
            "%s cache lock delete failed: key=%s error=%s",
            log_context,
            key,
            exc,
            exc_info=True,
        )
        return False


def acquire_best_effort_lock(
    key: str,
    *,
    timeout_seconds: int,
    logger: logging.Logger,
    log_context: str,
    allow_local_fallback: bool | None = None,
) -> tuple[bool, bool, str | None]:
    """
    Acquire lock via cache first; fallback to in-process lock on cache failure.

    Returns:
        (acquired, from_cache, lock_token)
    """
    timeout = max(1, int(timeout_seconds))
    lock_token = _make_lock_token()
    if allow_local_fallback is None:
        allow_local_fallback = bool(getattr(settings, "BEST_EFFORT_LOCK_ALLOW_LOCAL_FALLBACK", True))
    try:
        if cache.add(key, lock_token, timeout=timeout):
            return True, True, lock_token
        return False, True, None
    except Exception as exc:
        if not allow_local_fallback:
            logger.warning(
                "%s cache lock unavailable (fail-closed): key=%s degraded=True error=%s",
                log_context,
                key,
                exc,
                exc_info=True,
            )
            from core.utils.task_monitoring import increment_degraded_counter

            increment_degraded_counter("cache_lock_fail_closed")
            return False, False, None
        logger.warning(
            "%s cache lock unavailable, fallback to local lock: key=%s error=%s",
            log_context,
            key,
            exc,
            exc_info=True,
        )

    now = time.monotonic()
    with _LOCAL_LOCKS_GUARD:
        existing = _LOCAL_LOCKS.get(key)
        if existing and existing[1] > now:
            return False, False, None

        _LOCAL_LOCKS[key] = (lock_token, now + timeout)
        from core.utils.task_monitoring import increment_degraded_counter

        increment_degraded_counter("local_lock_fallback")
        if len(_LOCAL_LOCKS) > _LOCAL_LOCKS_MAX_SIZE:
            _cleanup_expired_local_locks(now)
            if len(_LOCAL_LOCKS) > _LOCAL_LOCKS_MAX_SIZE:
                # If still oversized, remove oldest-ish items by earliest expiry.
                for stale_key, _ in sorted(_LOCAL_LOCKS.items(), key=lambda item: item[1][1])[:1000]:
                    _LOCAL_LOCKS.pop(stale_key, None)
        return True, False, lock_token


def build_action_lock_key(namespace: str, action: str, owner_id: int, scope: str) -> str:
    return f"{namespace}:{action}:{int(owner_id)}:{scope}"


def acquire_action_lock(
    namespace: str,
    action: str,
    owner_id: int,
    scope: str,
    *,
    timeout_seconds: int,
    logger: logging.Logger,
    log_context: str,
    allow_local_fallback: bool | None = None,
) -> tuple[bool, str, str | None]:
    key = build_action_lock_key(namespace, action, owner_id, scope)
    acquired, from_cache, lock_token = acquire_best_effort_lock(
        key,
        timeout_seconds=timeout_seconds,
        logger=logger,
        log_context=log_context,
        allow_local_fallback=allow_local_fallback,
    )
    if not acquired:
        return False, "", None
    if from_cache:
        return True, key, lock_token
    return True, f"{_LOCAL_LOCK_KEY_PREFIX}{key}", lock_token


def release_best_effort_lock(
    key: str,
    *,
    from_cache: bool,
    lock_token: str | None,
    logger: logging.Logger,
    log_context: str,
) -> None:
    if not lock_token:
        logger.warning("%s lock_token missing, skip release to avoid unsafe unlock: key=%s", log_context, key)
        return

    if from_cache:
        released = _release_cache_lock_atomic_if_owner(
            key,
            lock_token=lock_token,
            logger=logger,
            log_context=log_context,
        )
        if released is True:
            return
        if released is None:
            _release_cache_lock_non_atomic_if_owner(
                key,
                lock_token=lock_token,
                logger=logger,
                log_context=log_context,
            )
        return

    with _LOCAL_LOCKS_GUARD:
        existing = _LOCAL_LOCKS.get(key)
        if not existing:
            return
        if existing[0] != lock_token:
            return
        _LOCAL_LOCKS.pop(key, None)


def release_action_lock(
    lock_key: str,
    *,
    lock_token: str | None,
    logger: logging.Logger,
    log_context: str,
) -> None:
    if not lock_key:
        return

    from_cache = True
    actual_key = lock_key
    if lock_key.startswith(_LOCAL_LOCK_KEY_PREFIX):
        from_cache = False
        actual_key = lock_key[len(_LOCAL_LOCK_KEY_PREFIX) :]

    release_best_effort_lock(
        actual_key,
        from_cache=from_cache,
        lock_token=lock_token,
        logger=logger,
        log_context=log_context,
    )


def release_cache_key_if_owner(
    key: str,
    *,
    lock_token: str | None,
    logger: logging.Logger,
    log_context: str,
) -> bool:
    """
    Release a cache-backed lock key only when the token matches ownership.

    Returns:
        True when key was deleted by owner, otherwise False.
    """
    if not lock_token:
        logger.warning("%s lock_token missing, skip release: key=%s", log_context, key)
        return False

    released = _release_cache_lock_atomic_if_owner(
        key,
        lock_token=lock_token,
        logger=logger,
        log_context=log_context,
    )
    if released is True:
        return True
    if released is None:
        return _release_cache_lock_non_atomic_if_owner(
            key,
            lock_token=lock_token,
            logger=logger,
            log_context=log_context,
        )
    return False
