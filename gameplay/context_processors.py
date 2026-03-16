from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError

from gameplay.selectors.sidebar import SIDEBAR_RANK_CACHE_TIMEOUT, load_sidebar_rank  # noqa: F401
from gameplay.selectors.stats import (  # noqa: F401
    _LOCAL_STATS_CACHE,
    _LOCAL_STATS_CACHE_GUARD,
    _LOCAL_STATS_CACHE_MAX_SIZE,
    ONLINE_USERS_CACHE_KEY,
    ONLINE_USERS_CACHE_TIMEOUT,
    ONLINE_USERS_FALLBACK_CACHE_TIMEOUT,
    TOTAL_USERS_CACHE_KEY,
    TOTAL_USERS_CACHE_TIMEOUT,
    User,
    _load_online_user_count_from_db,
    _load_online_user_count_from_redis,
    get_redis_connection,
    load_online_user_count,
    load_total_user_count,
)
from gameplay.services.utils.messages import unread_message_count

logger = logging.getLogger(__name__)

DEFAULT_PROTECTION_STATUS = {"is_protected": False, "type_display": "", "remaining_display": ""}

# ---------------------------------------------------------------------------
# Backwards-compatible aliases so existing monkeypatch / import call-sites
# that reference ``gameplay.context_processors.<name>`` keep working.
# ---------------------------------------------------------------------------
_load_total_user_count = load_total_user_count
_load_online_user_count = load_online_user_count
_load_online_user_count_from_redis = _load_online_user_count_from_redis  # noqa: F811 – re-export
_load_online_user_count_from_db = _load_online_user_count_from_db  # noqa: F811 – re-export
_load_sidebar_rank = load_sidebar_rank


def _build_default_context() -> dict[str, Any]:
    return {
        "message_unread_count": 0,
        "online_user_count": 0,
        "total_user_count": 0,
        "header_protection_status": DEFAULT_PROTECTION_STATUS.copy(),
    }


def _should_load_global_stats(request) -> bool:
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return False
    accept = request.headers.get("accept", "")
    if accept and "text/html" not in accept and "application/xhtml+xml" not in accept:
        return False
    return True


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
        context["sidebar_rank"] = load_sidebar_rank(manor)
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
    if _should_load_global_stats(request):
        context["total_user_count"] = _load_total_user_count()
        context["online_user_count"] = _load_online_user_count()

    if not request.user.is_authenticated:
        return context

    _populate_authenticated_context(context, request)
    return context
