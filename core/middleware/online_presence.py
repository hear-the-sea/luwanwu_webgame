from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse

from gameplay.services.online_presence import refresh_online_presence_from_request


class OnlinePresenceMiddleware:
    """Record authenticated user presence outside template rendering."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        refresh_online_presence_from_request(getattr(request, "user", None))
        return self.get_response(request)
