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


def _check_database_ready() -> tuple[bool, str | None]:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, None
    except DatabaseError as exc:
        return False, _maybe_debug_error(exc)


def _check_cache_ready() -> tuple[bool, str | None]:
    key = "health:ready:cache"
    marker = "1"
    try:
        cache.set(key, marker, timeout=5)
        if cache.get(key) != marker:
            raise RuntimeError("cache roundtrip failed")
        return True, None
    except Exception as exc:
        return False, _maybe_debug_error(exc)
    finally:
        try:
            cache.delete(key)
        except Exception:
            # health check should stay non-fatal even if cache delete fails
            pass


@require_GET
def health_ready(request):
    checks: dict[str, bool] = {"db": True, "cache": True}
    errors: dict[str, str] = {}

    db_ok, db_error = _check_database_ready()
    checks["db"] = db_ok
    if db_error:
        errors["db"] = db_error

    cache_ok, cache_error = _check_cache_ready()
    checks["cache"] = cache_ok
    if cache_error:
        errors["cache"] = cache_error

    ok = all(checks.values())
    payload = {"status": "ok" if ok else "error", "checks": checks}
    if errors:
        payload["errors"] = errors
    return JsonResponse(payload, status=200 if ok else 503)
