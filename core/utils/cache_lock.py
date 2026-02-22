from __future__ import annotations

import logging
import time
from threading import Lock

from django.core.cache import cache

_LOCAL_LOCKS: dict[str, float] = {}
_LOCAL_LOCKS_GUARD = Lock()
_LOCAL_LOCKS_MAX_SIZE = 20000


def _cleanup_expired_local_locks(now: float) -> None:
    expired_keys = [key for key, expires_at in _LOCAL_LOCKS.items() if expires_at <= now]
    for key in expired_keys:
        _LOCAL_LOCKS.pop(key, None)


def acquire_best_effort_lock(
    key: str,
    *,
    timeout_seconds: int,
    logger: logging.Logger,
    log_context: str,
) -> tuple[bool, bool]:
    """
    Acquire lock via cache first; fallback to in-process lock on cache failure.

    Returns:
        (acquired, from_cache)
    """
    timeout = max(1, int(timeout_seconds))
    try:
        if cache.add(key, "1", timeout=timeout):
            return True, True
        return False, True
    except Exception as exc:
        logger.warning(
            "%s cache lock unavailable, fallback to local lock: key=%s error=%s",
            log_context,
            key,
            exc,
            exc_info=True,
        )

    now = time.monotonic()
    with _LOCAL_LOCKS_GUARD:
        expires_at = _LOCAL_LOCKS.get(key, 0.0)
        if expires_at > now:
            return False, False

        _LOCAL_LOCKS[key] = now + timeout
        if len(_LOCAL_LOCKS) > _LOCAL_LOCKS_MAX_SIZE:
            _cleanup_expired_local_locks(now)
            if len(_LOCAL_LOCKS) > _LOCAL_LOCKS_MAX_SIZE:
                # If still oversized, remove oldest-ish items by earliest expiry.
                for stale_key, _ in sorted(_LOCAL_LOCKS.items(), key=lambda item: item[1])[:1000]:
                    _LOCAL_LOCKS.pop(stale_key, None)
        return True, False


def release_best_effort_lock(
    key: str,
    *,
    from_cache: bool,
    logger: logging.Logger,
    log_context: str,
) -> None:
    if from_cache:
        try:
            cache.delete(key)
        except Exception as exc:
            logger.warning(
                "%s cache lock release failed: key=%s error=%s",
                log_context,
                key,
                exc,
                exc_info=True,
            )
        return

    with _LOCAL_LOCKS_GUARD:
        _LOCAL_LOCKS.pop(key, None)
