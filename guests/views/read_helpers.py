from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from gameplay.services.manor.core import get_manor
from gameplay.services.resources import project_resource_production_for_read
from gameplay.views.read_helpers import get_prepared_manor_for_read
from guests.utils.guest_state import refresh_guest_state, refresh_guests_state


def get_prepared_guest_roster_for_read(
    request: HttpRequest,
    *,
    logger: Any,
    source: str,
    available_guests_fn: Callable[[Any], Any],
) -> tuple[Any, list[Any]]:
    manor = get_prepared_manor_for_read(
        request,
        project_fn=project_resource_production_for_read,
        logger=logger,
        source=source,
    )
    guests = list(available_guests_fn(manor))
    refresh_guests_state(guests, now=timezone.now(), refresh=True)
    return manor, guests


def get_prepared_guest_detail_for_read(
    request: HttpRequest,
    guest_pk: int,
    *,
    load_guest_detail_fn: Callable[[Any, int], Any],
) -> tuple[Any, Any]:
    manor = get_manor(request.user)
    guest = load_guest_detail_fn(manor, guest_pk)
    refresh_guest_state(guest, now=timezone.now(), refresh=True)
    return manor, guest
