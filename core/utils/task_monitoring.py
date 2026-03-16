"""
Celery task monitoring utilities.

Provides lightweight cache-backed counters for tracking task success, failure,
and retry events. Cache-backed snapshots are visible across Django/Celery
processes when the configured cache backend is shared (for example Redis).
In-process counters remain as a fallback when cache access fails.

Each metric field is stored under its own cache key so that increments map to
atomic ``cache.incr()`` calls (Redis INCR), eliminating the read-modify-write
race condition present in multi-worker deployments.

Key layout::

    TASK_METRICS_CACHE_KEY          → set of known task names  (registry)
    metrics:celery:{task}:success   → int counter
    metrics:celery:{task}:failure   → int counter
    metrics:celery:{task}:retry     → int counter

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

from django.core.cache import cache

from core.utils.degradation import CELERY_TASK_RETRY, record_degradation

logger = logging.getLogger(__name__)

# Registry key: stores a set of task names that have ever been recorded.
TASK_METRICS_CACHE_KEY = "metrics:celery:task_monitoring"

# Prefix for per-metric atomic counter keys.
_TASK_METRIC_KEY_PREFIX = "metrics:celery:"

# In-process fallback state (used only when cache is unavailable).
_metrics: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0, "retry": 0})
_metrics_lock = threading.Lock()

_FIELDS = ("success", "failure", "retry")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_task_entry(task_name: str) -> dict[str, int]:
    """Return the in-process counter dict for *task_name*, creating it if needed."""
    return _metrics[task_name]


def _empty_counts() -> dict[str, int]:
    return {"success": 0, "failure": 0, "retry": 0}


def _metric_key(task_name: str, field: str) -> str:
    """Return the cache key for a single metric counter."""
    return f"{_TASK_METRIC_KEY_PREFIX}{task_name}:{field}"


def _register_task_name(task_name: str) -> None:
    """Add *task_name* to the shared task-name registry."""
    try:
        registry: set[str] = cache.get(TASK_METRICS_CACHE_KEY) or set()
        if task_name not in registry:
            registry.add(task_name)
            cache.set(TASK_METRICS_CACHE_KEY, registry, timeout=None)
    except Exception:
        logger.warning("Failed to update task metrics registry", exc_info=True)


def _get_registry() -> set[str] | None:
    """Return the set of known task names, or None on cache error."""
    try:
        value = cache.get(TASK_METRICS_CACHE_KEY)
        if value is None:
            return set()
        if isinstance(value, set):
            return value
        # Tolerate legacy dict format written by old code.
        if isinstance(value, dict):
            return set(value.keys())
        return set()
    except Exception:
        logger.warning("Failed to read task metrics registry", exc_info=True)
        return None


def _increment_metric_atomic(task_name: str, field: str) -> None:
    """Atomically increment the cache counter for *task_name*/*field*.

    ``cache.incr()`` maps to Redis INCR (atomic) and is also lock-protected in
    Django's LocMemCache, making this safe for both backends.  Falls back to
    the in-process counter when cache access fails.
    """
    key = _metric_key(task_name, field)
    try:
        cache.incr(key, delta=1)
    except ValueError:
        # Key does not exist yet; initialise it to 1.
        try:
            cache.set(key, 1, timeout=None)
        except Exception:
            logger.warning("Failed to initialise task metric %s.%s", task_name, field, exc_info=True)
            with _metrics_lock:
                _ensure_task_entry(task_name)[field] += 1
            return
    except Exception:
        logger.warning("Failed to increment task metric %s.%s", task_name, field, exc_info=True)
        with _metrics_lock:
            _ensure_task_entry(task_name)[field] += 1
        return

    # Persist the task name so get_task_metrics() can enumerate all tasks.
    _register_task_name(task_name)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_task_success(task_name: str) -> None:
    """Increment the success counter for *task_name*."""
    _increment_metric_atomic(task_name, "success")


def record_task_failure(task_name: str) -> None:
    """Increment the failure counter for *task_name*."""
    _increment_metric_atomic(task_name, "failure")


def record_task_retry(task_name: str) -> None:
    """Increment the retry counter for *task_name* and record a degradation event."""
    _increment_metric_atomic(task_name, "retry")

    record_degradation(
        CELERY_TASK_RETRY,
        component="task_monitoring",
        detail=f"task {task_name} retried",
        task_name=task_name,
    )


def get_task_metrics() -> dict[str, dict[str, int]]:
    """Return a snapshot of task metrics, preferring the shared cache view."""
    registry = _get_registry()

    if registry is None:
        # Cache unavailable; fall back to in-process counters.
        with _metrics_lock:
            return {name: dict(counts) for name, counts in _metrics.items()}

    if not registry:
        return {}

    result: dict[str, dict[str, int]] = {}
    for task_name in registry:
        keys = [_metric_key(task_name, f) for f in _FIELDS]
        try:
            values = cache.get_many(keys)
        except Exception:
            logger.warning("Failed to read metric keys for task %s", task_name, exc_info=True)
            with _metrics_lock:
                result[task_name] = dict(_ensure_task_entry(task_name))
            continue

        result[task_name] = {field: int(values.get(_metric_key(task_name, field), 0) or 0) for field in _FIELDS}

    return result


def reset_task_metrics() -> None:
    """Reset all task metrics (useful in tests)."""
    with _metrics_lock:
        _metrics.clear()

    registry = _get_registry() or set()
    keys_to_delete = [TASK_METRICS_CACHE_KEY]
    for task_name in registry:
        for field in _FIELDS:
            keys_to_delete.append(_metric_key(task_name, field))

    try:
        cache.delete_many(keys_to_delete)
    except Exception:
        logger.warning("Failed to clear task metrics cache", exc_info=True)
        # Best-effort fallback: delete keys one by one.
        for key in keys_to_delete:
            try:
                cache.delete(key)
            except Exception:
                pass
