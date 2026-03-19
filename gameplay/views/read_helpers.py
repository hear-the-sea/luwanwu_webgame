from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.utils.infrastructure import DATABASE_INFRASTRUCTURE_EXCEPTIONS, is_expected_infrastructure_error

EXPECTED_READ_PROJECTION_ERRORS = DATABASE_INFRASTRUCTURE_EXCEPTIONS


def prepare_manor_for_read(
    manor: Any,
    *,
    project_fn: Callable[[Any], None],
    logger: logging.Logger,
    source: str,
    user_id: int | None = None,
    on_expected_failure: Callable[[Exception], None] | None = None,
) -> bool:
    """Run manor read projection with consistent view-layer degradation semantics."""
    try:
        project_fn(manor)
        return True
    except Exception as exc:
        if not is_expected_infrastructure_error(
            exc,
            exceptions=EXPECTED_READ_PROJECTION_ERRORS,
        ):
            raise
        logger.warning(
            "Manor read projection failed: source=%s manor_id=%s user_id=%s error=%s",
            source,
            getattr(manor, "id", None),
            user_id,
            exc,
            exc_info=True,
        )
        if on_expected_failure is not None:
            on_expected_failure(exc)
        return False
