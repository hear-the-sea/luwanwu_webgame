"""
Celery task monitoring utilities.

Provides lightweight in-process counters for tracking task success, failure,
and retry events.  Counters are thread-safe and designed to be scraped by the
health endpoint or a future metrics exporter (Prometheus, StatsD, etc.).

Usage::

    from core.utils.task_monitoring import record_task_success, get_task_metrics

    record_task_success("trade.refresh_shop_stock")
    metrics = get_task_metrics()
    # => {"trade.refresh_shop_stock": {"success": 1, "failure": 0, "retry": 0}}
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict

from core.utils.degradation import CELERY_TASK_RETRY, record_degradation

logger = logging.getLogger(__name__)

_metrics: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0, "retry": 0})
_metrics_lock = threading.Lock()


def _ensure_task_entry(task_name: str) -> dict[str, int]:
    """Return the counter dict for *task_name*, creating it if needed."""
    return _metrics[task_name]


def record_task_success(task_name: str) -> None:
    """Increment the success counter for *task_name*."""
    with _metrics_lock:
        _ensure_task_entry(task_name)["success"] += 1


def record_task_failure(task_name: str) -> None:
    """Increment the failure counter for *task_name*."""
    with _metrics_lock:
        _ensure_task_entry(task_name)["failure"] += 1


def record_task_retry(task_name: str) -> None:
    """Increment the retry counter for *task_name* and record a degradation event."""
    with _metrics_lock:
        _ensure_task_entry(task_name)["retry"] += 1

    record_degradation(
        CELERY_TASK_RETRY,
        component="task_monitoring",
        detail=f"task {task_name} retried",
        task_name=task_name,
    )


def get_task_metrics() -> dict[str, dict[str, int]]:
    """Return a snapshot of all task metrics (for health/metrics endpoints)."""
    with _metrics_lock:
        return {name: dict(counts) for name, counts in _metrics.items()}


def reset_task_metrics() -> None:
    """Reset all task metrics (useful in tests)."""
    with _metrics_lock:
        _metrics.clear()
