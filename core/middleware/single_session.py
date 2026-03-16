from __future__ import annotations

import logging
from typing import Callable

from django.contrib.auth import logout
from django.core.cache import cache
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse

from accounts.models import UserActiveSession
from accounts.utils import USER_SESSION_CACHE_PREFIX, USER_SESSION_CACHE_TTL
from core.utils.degradation import SESSION_SYNC_FAILURE, record_degradation

logger = logging.getLogger(__name__)
_SESSION_VERIFY_CACHE_SUFFIX = ":verified"
_SESSION_VERIFY_CACHE_TTL_SECONDS = min(USER_SESSION_CACHE_TTL, 300) if USER_SESSION_CACHE_TTL > 0 else 300


def _load_active_session_key(user_id: int) -> str | None:
    cache_key = f"{USER_SESSION_CACHE_PREFIX}{user_id}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None

    if cached:
        return str(cached)

    session_key = UserActiveSession.objects.filter(user_id=user_id).values_list("session_key", flat=True).first()
    if session_key:
        try:
            cache.set(cache_key, session_key, timeout=USER_SESSION_CACHE_TTL)
        except Exception:
            logger.debug("Failed to cache active session key for user %s", user_id, exc_info=True)
    return session_key


def _load_active_session_key_from_db(user_id: int) -> str | None:
    session_key = UserActiveSession.objects.filter(user_id=user_id).values_list("session_key", flat=True).first()
    if session_key:
        cache_key = f"{USER_SESSION_CACHE_PREFIX}{user_id}"
        try:
            cache.set(cache_key, session_key, timeout=USER_SESSION_CACHE_TTL)
        except Exception:
            logger.debug("Failed to refresh active session cache for user %s", user_id, exc_info=True)
    return session_key


def _ensure_active_session_key(user_id: int, current_session_key: str) -> str:
    cache_key = f"{USER_SESSION_CACHE_PREFIX}{user_id}"
    session_key = _load_active_session_key_from_db(user_id)
    if session_key:
        return session_key

    try:
        UserActiveSession.objects.create(user_id=user_id, session_key=current_session_key)
        session_key = current_session_key
    except IntegrityError:
        session_key = _load_active_session_key_from_db(user_id) or current_session_key

    try:
        cache.set(cache_key, session_key, timeout=USER_SESSION_CACHE_TTL)
    except Exception:
        logger.debug("Failed to write active session cache for user %s", user_id, exc_info=True)
    return session_key


def _should_verify_matching_session(user_id: int) -> bool:
    verify_key = f"{USER_SESSION_CACHE_PREFIX}{user_id}{_SESSION_VERIFY_CACHE_SUFFIX}"
    try:
        return bool(cache.add(verify_key, "1", timeout=_SESSION_VERIFY_CACHE_TTL_SECONDS))
    except Exception:
        logger.debug("Failed to write single-session verification marker for user %s", user_id, exc_info=True)
        # When cache markers are unavailable, fall back to DB verification instead of
        # trusting a potentially stale cache entry for the full session lifetime.
        return True


class SingleSessionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            session = getattr(request, "session", None)
            current_session_key = getattr(session, "session_key", None)
            if current_session_key:
                try:
                    active_session_key = _load_active_session_key(user.id)
                except Exception:
                    record_degradation(
                        SESSION_SYNC_FAILURE,
                        component="single_session_middleware",
                        detail="session enforcement failed, degrading to open",
                        user_id=user.id,
                    )
                else:
                    if not active_session_key:
                        active_session_key = _ensure_active_session_key(user.id, current_session_key)
                    elif active_session_key == current_session_key and _should_verify_matching_session(user.id):
                        active_session_key = _ensure_active_session_key(user.id, current_session_key)
                    if active_session_key and active_session_key != current_session_key:
                        db_session_key = _load_active_session_key_from_db(user.id)
                        if not db_session_key:
                            active_session_key = _ensure_active_session_key(user.id, current_session_key)
                            db_session_key = active_session_key
                        if db_session_key and db_session_key != current_session_key:
                            logout(request)

        return self.get_response(request)
