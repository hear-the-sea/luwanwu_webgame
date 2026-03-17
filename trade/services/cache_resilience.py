"""Shared cache operation helpers for fail-open / fail-closed service paths."""

from __future__ import annotations

from typing import Any, Callable


def best_effort_cache_get(
    cache_backend: Any,
    key: str,
    default: Any = None,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> Any:
    try:
        return cache_backend.get(key, default)
    except infrastructure_exceptions:
        logger.warning(
            "Failed to read cache key: %s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        return default
    except Exception:
        logger.error(
            "Unexpected cache.get failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
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
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> None:
    try:
        cache_backend.set(key, value, timeout=timeout)
    except infrastructure_exceptions:
        logger.warning(
            "Failed to write cache key: %s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
    except Exception:
        logger.error(
            "Unexpected cache.set failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )


def best_effort_cache_add(
    cache_backend: Any,
    key: str,
    value: Any,
    timeout: int,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> bool:
    try:
        return bool(cache_backend.add(key, value, timeout=timeout))
    except infrastructure_exceptions:
        logger.warning(
            "Failed to add cache key: %s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        return False
    except Exception:
        logger.error(
            "Unexpected cache.add failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        return False


def best_effort_cache_delete(
    cache_backend: Any,
    key: str,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> None:
    try:
        cache_backend.delete(key)
    except infrastructure_exceptions:
        logger.warning(
            "Failed to delete cache key: %s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
    except Exception:
        logger.error(
            "Unexpected cache.delete failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )


def strict_cache_get(
    cache_backend: Any,
    key: str,
    default: Any = None,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
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
    except Exception:
        logger.error(
            "Unexpected strict cache.get failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        raise


def strict_cache_add(
    cache_backend: Any,
    key: str,
    value: Any,
    timeout: int,
    *,
    logger,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
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
    except Exception:
        logger.error(
            "Unexpected strict cache.add failure: key=%s",
            key,
            exc_info=True,
            extra={"degraded": True, "component": component},
        )
        raise
