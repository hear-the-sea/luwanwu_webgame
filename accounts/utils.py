from __future__ import annotations

import logging
import time
import uuid
from threading import Lock

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# 用户 session 映射的缓存 key 前缀
USER_SESSION_CACHE_PREFIX = "user_session:"
# 登录锁前缀（防止并发登录竞态条件）
USER_LOGIN_LOCK_PREFIX = "login_lock:"
# 缓存过期时间（与 session 过期时间一致，默认 2 周）
USER_SESSION_CACHE_TTL = getattr(settings, "SESSION_COOKIE_AGE", 1209600)
# 登录锁超时时间（秒）
LOGIN_LOCK_TIMEOUT = 5
LOGIN_LOCK_RETRY_INTERVAL_SECONDS = 0.05
LOGIN_LOCK_MAX_WAIT_SECONDS = 0.30

_LOCAL_LOGIN_LOCKS: dict[str, tuple[str, float]] = {}
_LOCAL_LOGIN_LOCKS_GUARD = Lock()
_LOCAL_LOGIN_LOCKS_MAX_SIZE = 5000


def _session_key_prefix(session_key: str | None) -> str:
    return (str(session_key) if session_key is not None else "<none>")[:8]


def purge_other_sessions(user_id: int, current_session_key: str | None) -> None:
    """
    Enforce single active session per user by removing all other sessions.

    优化说明：
    - 使用 Redis 缓存维护 user_id -> session_key 映射
    - 避免遍历全表 Session，时间复杂度从 O(N) 降到 O(1)
    - 登录时记录新 session，同时清除旧 session

    安全修复：使用分布式锁防止并发登录导致的竞态条件
    """
    if not current_session_key:
        return

    cache_key = f"{USER_SESSION_CACHE_PREFIX}{user_id}"
    lock_key = f"{USER_LOGIN_LOCK_PREFIX}{user_id}"
    lock_token = uuid.uuid4().hex

    try:
        # 安全修复：使用分布式锁防止并发登录竞态条件
        # 如果无法获取锁，直接跳过（非阻塞），避免阻塞 worker
        lock_acquired = _acquire_login_lock(lock_key, lock_token)
        if not lock_acquired:
            # 在短暂重试后仍未拿到锁时，走降级清理，尽量保持单活跃 session 语义。
            logger.warning("Login lock busy for user %s, falling back to full session scan", user_id)
            _purge_sessions_fallback(user_id, current_session_key)
            cache.set(cache_key, current_session_key, timeout=USER_SESSION_CACHE_TTL)
            return

        try:
            # 获取该用户之前的 session key
            old_session_key = cache.get(cache_key)

            # 如果存在旧 session 且不是当前 session，删除它
            if old_session_key and old_session_key != current_session_key:
                try:
                    Session.objects.filter(session_key=old_session_key).delete()
                    logger.debug("Purged old session for user %s", user_id)
                except Exception as e:
                    logger.warning("Failed to delete old session for user %s: %s", user_id, e)

            # 记录当前 session key 到缓存
            cache.set(cache_key, current_session_key, timeout=USER_SESSION_CACHE_TTL)
        finally:
            # 仅释放自己持有的锁，避免锁过期后误删其他并发请求新获取的锁
            if lock_acquired:
                _release_login_lock(lock_key, lock_token)

    except Exception as e:
        # 缓存不可用时降级为原始逻辑（但仅在必要时）
        logger.warning("Cache unavailable, falling back to session scan: %s", e)
        _purge_sessions_fallback(user_id, current_session_key)


def _purge_sessions_fallback(user_id: int, current_session_key: str) -> None:
    """
    降级方案：当缓存不可用时的 session 清理。

    注意：此方法会遍历有效 session，仅在缓存故障时使用。
    为了保持“单活跃 session”的语义一致性，这里不再截断扫描。
    """
    now = timezone.now()
    sessions = Session.objects.filter(expire_date__gt=now).iterator(chunk_size=1000)
    deleted_count = 0

    for session in sessions:
        try:
            data = session.get_decoded()
            if str(data.get("_auth_user_id")) != str(user_id):
                continue
            if session.session_key == current_session_key:
                continue
            session.delete()
            deleted_count += 1
        except (ValueError, KeyError, TypeError) as e:
            # 安全修复：明确捕获特定的解码异常类型，而非所有异常
            logger.debug(
                "Failed to decode session %s...: %s",
                _session_key_prefix(getattr(session, "session_key", None)),
                type(e).__name__,
                exc_info=True,
            )
            continue
        except Exception as e:
            # 其他未预期的异常记录为警告级别
            logger.warning(
                "Unexpected error processing session %s...: %s",
                _session_key_prefix(getattr(session, "session_key", None)),
                e,
                exc_info=True,
            )
            continue

    if deleted_count > 0:
        logger.info("Fallback purged %d sessions for user %s", deleted_count, user_id)


def _release_login_lock(lock_key: str, lock_token: str) -> None:
    """Best-effort lock release with ownership check."""
    try:
        current_token = cache.get(lock_key)
        if current_token == lock_token:
            cache.delete(lock_key)
    except Exception:
        logger.debug("Failed to release login lock %s", lock_key, exc_info=True)
    finally:
        _release_local_login_lock(lock_key, lock_token)


def _acquire_local_login_lock(lock_key: str, lock_token: str, deadline: float) -> bool:
    while True:
        now = time.monotonic()
        with _LOCAL_LOGIN_LOCKS_GUARD:
            existing = _LOCAL_LOGIN_LOCKS.get(lock_key)
            if existing is None or existing[1] <= now:
                _LOCAL_LOGIN_LOCKS[lock_key] = (lock_token, now + LOGIN_LOCK_TIMEOUT)
                _cleanup_local_login_locks(now)
                return True

        if now >= deadline:
            return False
        time.sleep(LOGIN_LOCK_RETRY_INTERVAL_SECONDS)


def _release_local_login_lock(lock_key: str, lock_token: str) -> None:
    with _LOCAL_LOGIN_LOCKS_GUARD:
        existing = _LOCAL_LOGIN_LOCKS.get(lock_key)
        if existing and existing[0] == lock_token:
            _LOCAL_LOGIN_LOCKS.pop(lock_key, None)


def _cleanup_local_login_locks(now: float) -> None:
    expired = [key for key, (_token, expire_at) in _LOCAL_LOGIN_LOCKS.items() if expire_at <= now]
    for key in expired[:1000]:
        _LOCAL_LOGIN_LOCKS.pop(key, None)

    if len(_LOCAL_LOGIN_LOCKS) <= _LOCAL_LOGIN_LOCKS_MAX_SIZE:
        return

    for key, _value in sorted(_LOCAL_LOGIN_LOCKS.items(), key=lambda item: item[1][1])[:500]:
        _LOCAL_LOGIN_LOCKS.pop(key, None)


def _acquire_login_lock(lock_key: str, lock_token: str) -> bool:
    """Try to acquire login lock with a short bounded retry window."""
    deadline = time.monotonic() + LOGIN_LOCK_MAX_WAIT_SECONDS
    while True:
        try:
            if cache.add(lock_key, lock_token, timeout=LOGIN_LOCK_TIMEOUT):
                return True
        except Exception:
            logger.warning("Login lock cache unavailable, fallback to local lock: key=%s", lock_key, exc_info=True)
            return _acquire_local_login_lock(lock_key, lock_token, deadline)

        if time.monotonic() >= deadline:
            return False
        time.sleep(LOGIN_LOCK_RETRY_INTERVAL_SECONDS)
