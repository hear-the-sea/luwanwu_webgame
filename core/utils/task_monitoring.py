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

    metrics:celery:task_monitoring:index  → Redis set of known task names
    task_name_registry:{task_name}        → per-task presence marker
    metrics:celery:{task}:success         → int counter
    metrics:celery:{task}:failure         → int counter
    metrics:celery:{task}:retry           → int counter

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
from typing import Any

from django.core.cache import cache

from core.utils.degradation import CELERY_TASK_RETRY, record_degradation

logger = logging.getLogger(__name__)

# Legacy/non-Redis registry key: stores a set of known task names.
TASK_METRICS_CACHE_KEY = "metrics:celery:task_monitoring"
_TASK_METRICS_REDIS_REGISTRY_KEY = "metrics:celery:task_monitoring:index"
_TASK_NAME_REGISTRY_KEY_PREFIX = "task_name_registry:"

# Prefix for per-metric atomic counter keys.
_TASK_METRIC_KEY_PREFIX = "metrics:celery:"

# In-process fallback state (used only when cache is unavailable).
_metrics: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0, "retry": 0})
_metrics_lock = threading.Lock()
_registry_lock = threading.Lock()

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


def _registry_member_key(task_name: str) -> str:
    """Return the per-task registry marker cache key."""
    return f"{_TASK_NAME_REGISTRY_KEY_PREFIX}{task_name}"


def _coerce_registry(value: object) -> set[str]:
    """Normalise a registry cache payload into a task-name set."""
    if value is None:
        return set()
    if isinstance(value, set):
        return set(value)
    if isinstance(value, dict):
        return {str(task_name) for task_name in value.keys()}
    if isinstance(value, (frozenset, list, tuple)):
        return {str(task_name) for task_name in value}
    return set()


def _get_redis_registry_client() -> Any | None:
    # django-redis may return different backend client types; `Any` keeps this helper backend-agnostic.
    """Return the default Redis client when django-redis is available."""
    try:
        from django_redis import get_redis_connection
    except Exception:
        return None

    try:
        return get_redis_connection("default")
    except NotImplementedError:
        return None
    except Exception:
        logger.warning("Failed to acquire Redis client for task metrics registry", exc_info=True)
        return None


def _decode_redis_value(value: object) -> str:
    """Decode a Redis set member or key into text."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _get_redis_registry_key() -> str:
    """Return the concrete cache backend key for the Redis registry index."""
    if hasattr(cache, "make_key"):
        return cache.make_key(_TASK_METRICS_REDIS_REGISTRY_KEY)
    return _TASK_METRICS_REDIS_REGISTRY_KEY


def _get_redis_registry_member_prefix() -> str:
    """Return the concrete cache backend prefix for per-task marker keys."""
    if hasattr(cache, "make_key"):
        return cache.make_key(_TASK_NAME_REGISTRY_KEY_PREFIX)
    return _TASK_NAME_REGISTRY_KEY_PREFIX


def _get_registry_from_redis() -> set[str] | None:
    """Return task names from Redis-native registry structures, or None if unavailable."""
    redis_client = _get_redis_registry_client()
    if redis_client is None:
        return None

    registry: set[str] = set()
    read_succeeded = False

    try:
        registry.update(_decode_redis_value(value) for value in redis_client.smembers(_get_redis_registry_key()))
        read_succeeded = True
    except Exception:
        logger.warning("Failed to read Redis task metrics registry index", exc_info=True)

    try:
        prefix = _get_redis_registry_member_prefix()
        for key in redis_client.scan_iter(match=f"{prefix}*"):
            member_key = _decode_redis_value(key)
            if member_key.startswith(prefix):
                registry.add(member_key[len(prefix) :])
        read_succeeded = True
    except Exception:
        logger.warning("Failed to scan Redis task metrics registry markers", exc_info=True)

    if read_succeeded:
        return registry
    return None


def _register_task_name(task_name: str) -> None:
    """Add *task_name* to the shared task-name registry."""
    marker_key = _registry_member_key(task_name)
    try:
        cache.add(marker_key, 1, timeout=None)
    except Exception:
        logger.warning("Failed to write task metrics registry marker for %s", task_name, exc_info=True)

    redis_client = _get_redis_registry_client()
    if redis_client is not None:
        try:
            redis_client.sadd(_get_redis_registry_key(), task_name)
            return
        except Exception:
            logger.warning("Failed to update Redis task metrics registry index", exc_info=True)
            return

    try:
        with _registry_lock:
            registry = _coerce_registry(cache.get(TASK_METRICS_CACHE_KEY))
            if task_name in registry:
                return
            registry.add(task_name)
            cache.set(TASK_METRICS_CACHE_KEY, registry, timeout=None)
    except Exception:
        logger.warning("Failed to update task metrics registry", exc_info=True)


def _get_registry() -> set[str] | None:
    """Return the set of known task names, or None on cache error."""
    redis_registry = _get_registry_from_redis()
    if redis_registry is not None:
        return redis_registry

    try:
        return _coerce_registry(cache.get(TASK_METRICS_CACHE_KEY))
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
        # Key does not exist yet; initialise it with add() to avoid
        # a first-write lost-update race across workers.
        try:
            if not cache.add(key, 1, timeout=None):
                try:
                    cache.incr(key, delta=1)
                except ValueError:
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
    keys_to_delete = [TASK_METRICS_CACHE_KEY, _TASK_METRICS_REDIS_REGISTRY_KEY]
    for task_name in registry:
        keys_to_delete.append(_registry_member_key(task_name))
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


# --- Degraded path counters ---

_DEGRADED_COUNTER_TTL = 86400  # 24 hours


def increment_degraded_counter(component: str) -> None:
    """
    Increment the degraded-path counter for a named component.

    Counters are keyed by component name and reset daily.
    Safe to call from any context; cache failures are silently ignored.
    """
    from django.utils import timezone

    today = timezone.now().date().isoformat()
    key = f"degraded:{component}:{today}"
    try:
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=_DEGRADED_COUNTER_TTL)
        except Exception:
            cache.set(key, 1, timeout=_DEGRADED_COUNTER_TTL)
    except Exception:
        pass  # Never let metrics fail the caller


def get_degraded_counter(component: str, *, date_str: str | None = None) -> int:
    """
    Read the degraded-path counter for a named component.
    Returns 0 if counter is missing or cache is unavailable.
    """
    from django.utils import timezone

    if date_str is None:
        date_str = timezone.now().date().isoformat()
    key = f"degraded:{component}:{date_str}"
    try:
        value = cache.get(key)
        return int(value or 0)
    except Exception:
        return 0
