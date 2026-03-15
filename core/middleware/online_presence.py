from __future__ import annotations

from gameplay.context_processors import refresh_online_presence_from_request


class OnlinePresenceMiddleware:
    """Record authenticated user presence outside template rendering."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        refresh_online_presence_from_request(getattr(request, "user", None))
        return self.get_response(request)
