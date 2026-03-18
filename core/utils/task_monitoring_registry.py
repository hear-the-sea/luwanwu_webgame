from __future__ import annotations

from typing import Any, Callable


def build_metric_key(prefix: str, task_name: str, field: str) -> str:
    """Return the cache key for a single metric counter."""
    return f"{prefix}{task_name}:{field}"


def build_registry_member_key(prefix: str, task_name: str) -> str:
    """Return the per-task registry marker cache key."""
    return f"{prefix}{task_name}"


def coerce_registry(value: object) -> set[str]:
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


def get_redis_registry_client(logger: Any) -> Any | None:
    """Return the default Redis client when django-redis is available."""
    try:
        from django_redis import get_redis_connection
    except ImportError:
        return None

    try:
        return get_redis_connection("default")
    except NotImplementedError:
        return None
    except Exception:
        logger.warning("Failed to acquire Redis client for task metrics registry", exc_info=True)
        return None


def decode_redis_value(value: object) -> str:
    """Decode a Redis set member or key into text."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def get_redis_registry_key(cache_backend: Any, registry_key: str) -> str:
    """Return the concrete cache backend key for the Redis registry index."""
    if hasattr(cache_backend, "make_key"):
        return cache_backend.make_key(registry_key)
    return registry_key


def get_redis_registry_member_prefix(cache_backend: Any, marker_prefix: str) -> str:
    """Return the concrete cache backend prefix for per-task marker keys."""
    if hasattr(cache_backend, "make_key"):
        return cache_backend.make_key(marker_prefix)
    return marker_prefix


def get_registry_from_redis(
    *,
    cache_backend: Any,
    logger: Any,
    registry_key: str,
    marker_prefix: str,
    get_client: Callable[[], Any | None],
    decode_value: Callable[[object], str],
) -> set[str] | None:
    """Return task names from Redis-native registry structures, or None if unavailable."""
    redis_client = get_client()
    if redis_client is None:
        return None

    registry: set[str] = set()
    read_succeeded = False

    try:
        concrete_registry_key = get_redis_registry_key(cache_backend, registry_key)
        registry.update(decode_value(value) for value in redis_client.smembers(concrete_registry_key))
        read_succeeded = True
    except Exception:
        logger.warning("Failed to read Redis task metrics registry index", exc_info=True)

    try:
        member_prefix = get_redis_registry_member_prefix(cache_backend, marker_prefix)
        for key in redis_client.scan_iter(match=f"{member_prefix}*"):
            member_key = decode_value(key)
            if member_key.startswith(member_prefix):
                registry.add(member_key[len(member_prefix) :])
        read_succeeded = True
    except Exception:
        logger.warning("Failed to scan Redis task metrics registry markers", exc_info=True)

    if read_succeeded:
        return registry
    return None
