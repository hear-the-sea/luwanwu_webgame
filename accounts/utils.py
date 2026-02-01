from __future__ import annotations

import logging

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

    try:
        # 安全修复：使用分布式锁防止并发登录竞态条件
        # 如果无法获取锁，直接跳过（非阻塞），避免阻塞 worker
        lock_acquired = cache.add(lock_key, "1", timeout=LOGIN_LOCK_TIMEOUT)
        if not lock_acquired:
            # 非阻塞处理：无法获取锁时直接返回，session 清理不是关键路径
            # 避免使用 time.sleep 阻塞 worker，防止高并发下 worker 耗尽
            logger.debug(f"Login lock busy for user {user_id}, skipping session purge")
            return

        try:
            # 获取该用户之前的 session key
            old_session_key = cache.get(cache_key)

            # 如果存在旧 session 且不是当前 session，删除它
            if old_session_key and old_session_key != current_session_key:
                try:
                    Session.objects.filter(session_key=old_session_key).delete()
                    logger.debug(f"Purged old session for user {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete old session for user {user_id}: {e}")

            # 记录当前 session key 到缓存
            cache.set(cache_key, current_session_key, timeout=USER_SESSION_CACHE_TTL)
        finally:
            # 释放锁
            if lock_acquired:
                cache.delete(lock_key)

    except Exception as e:
        # 缓存不可用时降级为原始逻辑（但仅在必要时）
        logger.warning(f"Cache unavailable, falling back to session scan: {e}")
        _purge_sessions_fallback(user_id, current_session_key)


def _purge_sessions_fallback(user_id: int, current_session_key: str) -> None:
    """
    降级方案：当缓存不可用时的 session 清理。

    注意：此方法会遍历部分 session，仅在缓存故障时使用。
    限制扫描数量以避免性能问题。
    """
    now = timezone.now()
    # 限制扫描数量，避免在用户量大时阻塞
    sessions = Session.objects.filter(expire_date__gt=now)[:1000]
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
        except Exception:
            # Skip corrupted sessions during fallback scan
            logger.debug(f"Failed to decode/delete session {session.session_key[:8]}...", exc_info=True)
            continue

    if deleted_count > 0:
        logger.info(f"Fallback purged {deleted_count} sessions for user {user_id}")
