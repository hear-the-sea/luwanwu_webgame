"""
Degradation tracking utilities.

Provides lightweight counters and structured logging for code paths that
degrade gracefully instead of failing hard.  These counters live in-process
and are designed to be scraped by a future metrics exporter (Prometheus,
StatsD, etc.) or simply inspected via the health endpoint.

Usage::

    from core.utils.degradation import record_degradation

    record_degradation(
        "cache_fallback",
        component="context_processors",
        detail="total_user_count cache read failed",
    )
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict

logger = logging.getLogger("degradation")

_counters: dict[str, int] = defaultdict(int)
_counters_lock = threading.Lock()

# Well-known degradation categories.
CACHE_FALLBACK = "cache_fallback"
REDIS_FAILURE = "redis_failure"
CHAT_HISTORY_DEGRADED = "chat_history_degraded"
WORLD_CHAT_REFUND = "world_chat_refund"
SESSION_SYNC_FAILURE = "session_sync_failure"
CELERY_TASK_RETRY = "celery_task_retry"


def record_degradation(
    category: str,
    *,
    component: str = "",
    detail: str = "",
    user_id: int | None = None,
    manor_id: int | None = None,
    task_name: str = "",
) -> None:
    """Increment the counter for *category* and emit a structured log line."""
    with _counters_lock:
        _counters[category] += 1

    extra: dict[str, object] = {
        "degraded": True,
        "degradation_category": category,
    }
    if component:
        extra["component"] = component
    if user_id is not None:
        extra["user_id"] = user_id
    if manor_id is not None:
        extra["manor_id"] = manor_id
    if task_name:
        extra["task_name"] = task_name

    msg = f"[{category}] {detail}" if detail else f"[{category}]"
    if component:
        msg = f"{component}: {msg}"

    logger.warning(msg, extra=extra)


def get_degradation_counts() -> dict[str, int]:
    """Return a snapshot of all degradation counters (for health/metrics)."""
    with _counters_lock:
        return dict(_counters)


def reset_degradation_counts() -> None:
    """Reset all counters (useful in tests)."""
    with _counters_lock:
        _counters.clear()
