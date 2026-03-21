from __future__ import annotations

from typing import TypeAlias

from django.db import DatabaseError

InfrastructureExceptions: TypeAlias = tuple[type[Exception], ...]

CACHE_RUNTIME_ERROR_MARKERS = (
    "cache backend",
    "cache down",
    "cache get failed",
    "cache read failed",
    "cache set failed",
    "cache unavailable",
    "cache add failed",
    "cache delete failed",
    "cache delete_many failed",
    "cache write failed",
    "connection aborted",
    "connection refused",
    "connection reset",
    "redis",
    "socket",
    "timed out",
    "timeout",
)


def _append_optional_exception(
    exception_types: list[type[Exception]],
    *,
    module_name: str,
    attribute_name: str,
) -> None:
    try:
        module = __import__(module_name, fromlist=[attribute_name])
        exception_type = getattr(module, attribute_name)
    except Exception:
        return

    if isinstance(exception_type, type) and issubclass(exception_type, Exception):
        exception_types.append(exception_type)


def _dedupe_exception_types(exception_types: list[type[Exception]]) -> InfrastructureExceptions:
    unique_types: list[type[Exception]] = []
    for exc_type in exception_types:
        if exc_type not in unique_types:
            unique_types.append(exc_type)
    return tuple(unique_types)


def build_infrastructure_exceptions(
    *,
    include_database: bool = False,
    include_cache_runtime: bool = False,
) -> InfrastructureExceptions:
    exception_types: list[type[Exception]] = []
    if include_database:
        exception_types.append(DatabaseError)

    exception_types.extend([ConnectionError, OSError, TimeoutError])
    # `RuntimeError` is intentionally excluded from the concrete exception tuple.
    # Some backends leak infra failures through RuntimeError-like wrappers, but
    # swallowing the whole class would also hide unrelated programming errors.
    # Legacy RuntimeError compatibility is handled explicitly via message markers.
    _ = include_cache_runtime

    _append_optional_exception(
        exception_types,
        module_name="redis.exceptions",
        attribute_name="RedisError",
    )
    _append_optional_exception(
        exception_types,
        module_name="django_redis.exceptions",
        attribute_name="ConnectionInterrupted",
    )
    return _dedupe_exception_types(exception_types)


INFRASTRUCTURE_EXCEPTIONS = build_infrastructure_exceptions()
DATABASE_INFRASTRUCTURE_EXCEPTIONS = build_infrastructure_exceptions(include_database=True)
CACHE_INFRASTRUCTURE_EXCEPTIONS = build_infrastructure_exceptions(include_cache_runtime=True)
DATABASE_CACHE_INFRASTRUCTURE_EXCEPTIONS = build_infrastructure_exceptions(
    include_database=True,
    include_cache_runtime=True,
)
NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS = INFRASTRUCTURE_EXCEPTIONS


def is_cache_runtime_error(exc: Exception) -> bool:
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc).lower()
    return any(marker in message for marker in CACHE_RUNTIME_ERROR_MARKERS)


def is_infrastructure_runtime_error(exc: Exception) -> bool:
    """Legacy alias kept for cache-only runtime compatibility checks."""
    return is_cache_runtime_error(exc)


def is_expected_infrastructure_error(
    exc: Exception,
    *,
    exceptions: InfrastructureExceptions = INFRASTRUCTURE_EXCEPTIONS,
    allow_runtime_markers: bool = False,
) -> bool:
    # Runtime marker inference is intentionally limited to direct cache helpers.
    # Keep the flag as a no-op for compatibility with older callers.
    _ = allow_runtime_markers
    return isinstance(exc, exceptions)


def is_expected_cache_infrastructure_error(
    exc: Exception,
    *,
    exceptions: InfrastructureExceptions = CACHE_INFRASTRUCTURE_EXCEPTIONS,
) -> bool:
    return isinstance(exc, exceptions) or is_cache_runtime_error(exc)


INFRASTRUCTURE_RUNTIME_ERROR_MARKERS = CACHE_RUNTIME_ERROR_MARKERS


__all__ = [
    "CACHE_INFRASTRUCTURE_EXCEPTIONS",
    "CACHE_RUNTIME_ERROR_MARKERS",
    "DATABASE_CACHE_INFRASTRUCTURE_EXCEPTIONS",
    "DATABASE_INFRASTRUCTURE_EXCEPTIONS",
    "INFRASTRUCTURE_EXCEPTIONS",
    "INFRASTRUCTURE_RUNTIME_ERROR_MARKERS",
    "InfrastructureExceptions",
    "NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS",
    "build_infrastructure_exceptions",
    "is_cache_runtime_error",
    "is_expected_cache_infrastructure_error",
    "is_expected_infrastructure_error",
    "is_infrastructure_runtime_error",
]
