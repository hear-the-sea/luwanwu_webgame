from __future__ import annotations

from django.http import JsonResponse


def json_success(*, status: int = 200, **extra) -> JsonResponse:
    payload = {"success": True}
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)


def json_error(error: str, *, status: int = 400, include_message: bool = False, **extra) -> JsonResponse:
    payload = {"success": False, "error": error}
    if include_message:
        payload["message"] = error
    if extra:
        payload.update(extra)
    return JsonResponse(payload, status=status)
