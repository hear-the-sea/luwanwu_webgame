from __future__ import annotations

from django.http import HttpRequest


def is_ajax_request(request: HttpRequest) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def accepts_json(request: HttpRequest) -> bool:
    return "application/json" in request.headers.get("Accept", "").lower()


def is_json_request(request: HttpRequest) -> bool:
    return accepts_json(request) or is_ajax_request(request)
