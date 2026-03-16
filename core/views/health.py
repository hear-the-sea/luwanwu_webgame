from __future__ import annotations

import asyncio
import ipaddress

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.utils import DatabaseError
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.tasks import CELERY_BEAT_HEARTBEAT_CACHE_KEY, celery_health_ping
from core.utils.network import get_client_ip, is_trusted_proxy_ip


def _maybe_debug_error(exc: Exception) -> str | None:
    if settings.DEBUG:
        return str(exc)
    return None


@require_GET
def health_live(request):
    return JsonResponse({"status": "ok"})


def _is_internal_request(request) -> bool:
    remote_addr = request.META.get("REMOTE_ADDR", "")
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if forwarded_for and not is_trusted_proxy_ip(remote_addr):
        return False

    client_ip = get_client_ip(request, trust_proxy=bool(forwarded_for))
    if client_ip == "unknown":
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


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


async def _channel_layer_roundtrip(channel_layer, timeout_seconds: float) -> dict:
    channel_name = await channel_layer.new_channel("health.ready")
    payload = {"type": "health.ready", "marker": "ok"}
    await channel_layer.send(channel_name, payload)
    try:
        received = await asyncio.wait_for(channel_layer.receive(channel_name), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"channel layer receive timed out after {timeout_seconds:.2f}s") from exc
    if not isinstance(received, dict) or received.get("marker") != payload["marker"]:
        raise RuntimeError("channel layer roundtrip failed")
    return received


def _check_channel_layer_ready() -> tuple[bool, str | None]:
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            raise RuntimeError("channel layer is unavailable")
        timeout_seconds = max(0.01, float(getattr(settings, "HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS", 1.0)))
        async_to_sync(_channel_layer_roundtrip)(channel_layer, timeout_seconds)
        return True, None
    except Exception as exc:
        return False, _maybe_debug_error(exc)


def _check_celery_broker_ready() -> tuple[bool, str | None]:
    try:
        from config.celery import app as celery_app

        with celery_app.connection_for_read() as connection:
            connection.connect()
        return True, None
    except Exception as exc:
        return False, _maybe_debug_error(exc)


def _check_celery_workers_ready() -> tuple[bool, str | None]:
    try:
        from config.celery import app as celery_app

        responses = celery_app.control.inspect(timeout=1.0).ping() or {}
        if not responses:
            raise RuntimeError("no Celery workers responded to ping")
        return True, None
    except Exception as exc:
        return False, _maybe_debug_error(exc)


def _check_celery_beat_ready() -> tuple[bool, str | None]:
    max_age_seconds = max(60, int(getattr(settings, "HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS", 180)))
    try:
        last_seen_raw = cache.get(CELERY_BEAT_HEARTBEAT_CACHE_KEY)
        if last_seen_raw is None:
            raise RuntimeError("Celery beat heartbeat missing")

        last_seen = float(last_seen_raw)
        age_seconds = timezone.now().timestamp() - last_seen
        if age_seconds > max_age_seconds:
            raise RuntimeError(f"Celery beat heartbeat stale: {int(age_seconds)}s old")
        return True, None
    except Exception as exc:
        return False, _maybe_debug_error(exc)


def _check_celery_roundtrip_ready() -> tuple[bool, str | None]:
    timeout_seconds = max(0.5, float(getattr(settings, "HEALTH_CHECK_CELERY_ROUNDTRIP_TIMEOUT_SECONDS", 3.0)))
    async_result = None
    try:
        async_result = celery_health_ping.apply_async()
        response = async_result.get(timeout=timeout_seconds, disable_sync_subtasks=False)
        if response != "pong":
            raise RuntimeError(f"unexpected Celery roundtrip payload: {response!r}")
        return True, None
    except Exception as exc:
        return False, _maybe_debug_error(exc)
    finally:
        if async_result is not None:
            try:
                async_result.forget()
            except Exception:
                pass


@require_GET
def health_ready(request):
    if getattr(settings, "HEALTH_CHECK_REQUIRE_INTERNAL", False) and not _is_internal_request(request):
        raise Http404()

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

    if settings.HEALTH_CHECK_CHANNEL_LAYER:
        channel_ok, channel_error = _check_channel_layer_ready()
        checks["channel_layer"] = channel_ok
        if channel_error:
            errors["channel_layer"] = channel_error

    if settings.HEALTH_CHECK_CELERY_BROKER:
        celery_ok, celery_error = _check_celery_broker_ready()
        checks["celery_broker"] = celery_ok
        if celery_error:
            errors["celery_broker"] = celery_error

    if getattr(settings, "HEALTH_CHECK_CELERY_WORKERS", False):
        workers_ok, workers_error = _check_celery_workers_ready()
        checks["celery_workers"] = workers_ok
        if workers_error:
            errors["celery_workers"] = workers_error

    if getattr(settings, "HEALTH_CHECK_CELERY_BEAT", False):
        beat_ok, beat_error = _check_celery_beat_ready()
        checks["celery_beat"] = beat_ok
        if beat_error:
            errors["celery_beat"] = beat_error

    if getattr(settings, "HEALTH_CHECK_CELERY_ROUNDTRIP", False):
        roundtrip_ok, roundtrip_error = _check_celery_roundtrip_ready()
        checks["celery_roundtrip"] = roundtrip_ok
        if roundtrip_error:
            errors["celery_roundtrip"] = roundtrip_error

    ok = all(checks.values())
    payload = {"status": "ok" if ok else "error", "checks": checks}
    if errors:
        payload["errors"] = errors
    return JsonResponse(payload, status=200 if ok else 503)
