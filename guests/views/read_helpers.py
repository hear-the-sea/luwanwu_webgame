from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest

from gameplay.services.manor.core import project_manor_activity_for_read
from gameplay.views.read_helpers import get_prepared_manor_for_read


def get_prepared_guest_roster_for_read(
    request: HttpRequest,
    *,
    logger: Any,
    source: str,
    available_guests_fn: Callable[[Any], Any],
) -> tuple[Any, list[Any]]:
    manor = get_prepared_manor_for_read(
        request,
        project_fn=project_manor_activity_for_read,
        logger=logger,
        source=source,
    )
    return manor, list(available_guests_fn(manor))


def get_prepared_guest_detail_for_read(
    request: HttpRequest,
    guest_pk: int,
    *,
    logger: Any,
    source: str,
    load_guest_detail_fn: Callable[[Any, int], Any],
) -> tuple[Any, Any]:
    manor = get_prepared_manor_for_read(
        request,
        project_fn=project_manor_activity_for_read,
        logger=logger,
        source=source,
    )
    return manor, load_guest_detail_fn(manor, guest_pk)
