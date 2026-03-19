from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest

from core.utils.infrastructure import (
    DATABASE_CACHE_INFRASTRUCTURE_EXCEPTIONS,
    DATABASE_INFRASTRUCTURE_EXCEPTIONS,
    is_expected_infrastructure_error,
)
from gameplay.services.manor.core import get_manor
from gameplay.services.raid import refresh_raid_runs, refresh_scout_records

EXPECTED_READ_PROJECTION_ERRORS = DATABASE_INFRASTRUCTURE_EXCEPTIONS
EXPECTED_READ_ACTIVITY_REFRESH_ERRORS = DATABASE_CACHE_INFRASTRUCTURE_EXCEPTIONS


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


def get_prepared_manor_for_read(
    request: HttpRequest,
    *,
    project_fn: Callable[[Any], None],
    logger: logging.Logger,
    source: str,
    on_expected_failure: Callable[[Exception], None] | None = None,
) -> Any:
    """Load the current manor and run the standard read projection flow."""
    manor = get_manor(request.user)
    prepare_manor_for_read(
        manor,
        project_fn=project_fn,
        logger=logger,
        source=source,
        user_id=getattr(request.user, "id", None),
        on_expected_failure=on_expected_failure,
    )
    return manor


def get_prepared_manor_with_raid_activity_for_read(
    request: HttpRequest,
    *,
    logger: logging.Logger,
    source: str,
    project_fn: Callable[[Any], None] | None = None,
    prefer_async: bool = True,
    on_projection_expected_failure: Callable[[Exception], None] | None = None,
    on_activity_expected_failure: Callable[[Exception], None] | None = None,
) -> Any:
    """Load the current manor through the unified raid/scout read entrypoint."""
    manor = get_manor(request.user)
    user_id = getattr(request.user, "id", None)

    if project_fn is not None:
        prepare_manor_for_read(
            manor,
            project_fn=project_fn,
            logger=logger,
            source=source,
            user_id=user_id,
            on_expected_failure=on_projection_expected_failure,
        )

    prepare_raid_activity_for_read(
        manor,
        logger=logger,
        source=source,
        user_id=user_id,
        prefer_async=prefer_async,
        on_expected_failure=on_activity_expected_failure,
    )
    return manor


def prepare_manor_activity_for_read(
    manor: Any,
    *,
    refresh_fn: Callable[[Any], None],
    logger: logging.Logger,
    source: str,
    user_id: int | None = None,
    on_expected_failure: Callable[[Exception], None] | None = None,
) -> bool:
    """Run side-effectful manor activity refresh with explicit read-path degradation semantics."""
    try:
        refresh_fn(manor)
        return True
    except Exception as exc:
        if not is_expected_infrastructure_error(
            exc,
            exceptions=EXPECTED_READ_ACTIVITY_REFRESH_ERRORS,
        ):
            raise
        logger.warning(
            "Manor activity refresh failed: source=%s manor_id=%s user_id=%s error=%s",
            source,
            getattr(manor, "id", None),
            user_id,
            exc,
            exc_info=True,
        )
        if on_expected_failure is not None:
            on_expected_failure(exc)
        return False


def prepare_raid_activity_for_read(
    manor: Any,
    *,
    logger: logging.Logger,
    source: str,
    user_id: int | None = None,
    prefer_async: bool = True,
    on_expected_failure: Callable[[Exception], None] | None = None,
) -> bool:
    """Refresh raid/scout read models at explicit read entrypoints only."""

    def _refresh_activity(target_manor: Any) -> None:
        refresh_scout_records(target_manor, prefer_async=prefer_async)
        refresh_raid_runs(target_manor, prefer_async=prefer_async)

    return prepare_manor_activity_for_read(
        manor,
        refresh_fn=_refresh_activity,
        logger=logger,
        source=source,
        user_id=user_id,
        on_expected_failure=on_expected_failure,
    )
