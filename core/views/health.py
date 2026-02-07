from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.utils import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def _maybe_debug_error(exc: Exception) -> str | None:
    if settings.DEBUG:
        return str(exc)
    return None


@require_GET
def health_live(request):
    return JsonResponse({"status": "ok"})


@require_GET
def health_ready(request):
    checks: dict[str, bool] = {"db": True, "cache": True}
    errors: dict[str, str] = {}

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        checks["db"] = False
        msg = _maybe_debug_error(exc)
        if msg:
            errors["db"] = msg

    try:
        key = "health:ready:cache"
        cache.set(key, "1", timeout=5)
        if cache.get(key) != "1":
            raise RuntimeError("cache roundtrip failed")
    except Exception as exc:
        checks["cache"] = False
        msg = _maybe_debug_error(exc)
        if msg:
            errors["cache"] = msg

    ok = all(checks.values())
    payload = {"status": "ok" if ok else "error", "checks": checks}
    if errors:
        payload["errors"] = errors
    return JsonResponse(payload, status=200 if ok else 503)
