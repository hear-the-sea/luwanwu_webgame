from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

from django.core.cache import cache


def safe_apply_async(
    task: Any,
    *,
    args: Optional[Iterable[Any]] = None,
    kwargs: Optional[Mapping[str, Any]] = None,
    countdown: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
    log_message: str = "celery task dispatch failed",
) -> bool:
    """
    Best-effort Celery dispatch wrapper.

    Many callsites treat task dispatch as an optimization (fallback scanners/refresh loops exist),
    so we standardize the behavior: swallow dispatch exceptions but log them consistently.
    """
    try:
        task.apply_async(args=list(args or []), kwargs=dict(kwargs or {}), countdown=countdown)
        return True
    except Exception:
        if logger:
            logger.warning(log_message, exc_info=True)
        return False


def safe_apply_async_with_dedup(
    task: Any,
    *,
    dedup_key: str,
    dedup_timeout: int,
    args: Optional[Iterable[Any]] = None,
    kwargs: Optional[Mapping[str, Any]] = None,
    countdown: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
    log_message: str = "celery task dispatch failed",
) -> bool:
    """
    Best-effort Celery dispatch with cache-based dedup gate.

    Returns True when dispatch succeeded, or when another worker/request already dispatched
    the same dedup key in the dedup window. Returns False only when dispatch fails.
    """
    dedup_gate_acquired = False
    if dedup_key and dedup_timeout > 0:
        try:
            dedup_gate_acquired = bool(cache.add(dedup_key, "1", timeout=dedup_timeout))
            if not dedup_gate_acquired:
                return True
        except Exception:
            if logger:
                logger.debug("celery dispatch dedup cache unavailable: %s", dedup_key, exc_info=True)

    ok = safe_apply_async(
        task,
        args=args,
        kwargs=kwargs,
        countdown=countdown,
        logger=logger,
        log_message=log_message,
    )
    if ok:
        return True

    # Roll back dedup gate on dispatch failure to avoid dropping retries in the dedup window.
    if dedup_gate_acquired:
        try:
            cache.delete(dedup_key)
        except Exception:
            if logger:
                logger.debug("celery dispatch dedup rollback failed: %s", dedup_key, exc_info=True)
    return False
