"""Shared cache operation helpers for fail-open / fail-closed service paths."""

from __future__ import annotations

from typing import Any, Callable

from core.utils.infrastructure import is_cache_runtime_error


def best_effort_cache_get(
    cache_backend: Any,
    key: str,
    default: Any = None,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[Exception], ...],
) -> Any:
    try:
        return cache_backend.get(key, default)
    except Exception as exc:
        if is_cache_runtime_error(exc):
            raise
        log_extra = {"degraded": True, "component": component}
        if isinstance(exc, infrastructure_exceptions):
            logger.warning("Failed to read cache key: %s", key, exc_info=True, extra=log_extra)
        else:
            logger.error(
                "Unexpected exception reading cache key: %s",
                key,
                exc_info=True,
                extra={**log_extra, "unexpected": True},
            )
        return default


def best_effort_cache_set(
    cache_backend: Any,
    key: str,
    value: Any,
    timeout: int,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[Exception], ...],
) -> None:
    try:
        cache_backend.set(key, value, timeout=timeout)
    except Exception as exc:
        if is_cache_runtime_error(exc):
            raise
        log_extra = {"degraded": True, "component": component}
        if isinstance(exc, infrastructure_exceptions):
            logger.warning("Failed to write cache key: %s", key, exc_info=True, extra=log_extra)
        else:
            logger.error(
                "Unexpected exception writing cache key: %s",
                key,
                exc_info=True,
                extra={**log_extra, "unexpected": True},
            )


def best_effort_cache_add(
    cache_backend: Any,
    key: str,
    value: Any,
    timeout: int,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[Exception], ...],
) -> bool:
    try:
        return bool(cache_backend.add(key, value, timeout=timeout))
    except Exception as exc:
        if is_cache_runtime_error(exc):
            raise
        log_extra = {"degraded": True, "component": component}
        if isinstance(exc, infrastructure_exceptions):
            logger.warning("Failed to add cache key: %s", key, exc_info=True, extra=log_extra)
        else:
            logger.error(
                "Unexpected exception adding cache key: %s",
                key,
                exc_info=True,
                extra={**log_extra, "unexpected": True},
            )
        return False


def best_effort_cache_delete(
    cache_backend: Any,
    key: str,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[Exception], ...],
) -> None:
    try:
        cache_backend.delete(key)
    except Exception as exc:
        if is_cache_runtime_error(exc):
            raise
        log_extra = {"degraded": True, "component": component}
        if isinstance(exc, infrastructure_exceptions):
            logger.warning("Failed to delete cache key: %s", key, exc_info=True, extra=log_extra)
        else:
            logger.error(
                "Unexpected exception deleting cache key: %s",
                key,
                exc_info=True,
                extra={**log_extra, "unexpected": True},
            )


def strict_cache_get(
    cache_backend: Any,
    key: str,
    default: Any = None,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[Exception], ...],
    unavailable_error_factory: Callable[[], Exception],
) -> Any:
    try:
        return cache_backend.get(key, default)
    except infrastructure_exceptions as exc:
        logger.error(
            "Strict cache.get failed: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        raise unavailable_error_factory() from exc


def strict_cache_add(
    cache_backend: Any,
    key: str,
    value: Any,
    timeout: int,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[Exception], ...],
    unavailable_error_factory: Callable[[], Exception],
) -> bool:
    try:
        return bool(cache_backend.add(key, value, timeout=timeout))
    except infrastructure_exceptions as exc:
        logger.error(
            "Strict cache.add failed: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        raise unavailable_error_factory() from exc
