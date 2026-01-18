from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional


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

