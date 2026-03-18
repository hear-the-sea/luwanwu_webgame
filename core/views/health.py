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
from core.utils.degradation import get_degradation_counts
from core.utils.network import get_client_ip, is_trusted_proxy_ip
from core.utils.task_monitoring import get_degraded_counter, get_task_metrics
from websocket.routing_status import get_websocket_routing_status

_DEGRADED_COMPONENTS = [
    "cache_lock_fail_closed",
    "local_lock_fallback",
    "login_security_degraded",
    "celery_dispatch_failed",
]
_READY_CACHE_KEY = "health:ready:payload:v1"


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


def _should_include_health_details() -> bool:
    return bool(getattr(settings, "HEALTH_CHECK_INCLUDE_DETAILS", False))


def _load_cached_ready_payload() -> tuple[dict[str, object], int] | None:
    ttl_seconds = max(0, int(getattr(settings, "HEALTH_CHECK_CACHE_TTL_SECONDS", 0)))
    if ttl_seconds <= 0:
        return None
    cached = cache.get(_READY_CACHE_KEY)
    if not isinstance(cached, dict):
        return None
    payload = cached.get("payload")
    status_code = cached.get("status_code")
    if not isinstance(payload, dict) or not isinstance(status_code, int):
        return None
    return payload, status_code


def _store_cached_ready_payload(payload: dict[str, object], status_code: int) -> None:
    ttl_seconds = max(0, int(getattr(settings, "HEALTH_CHECK_CACHE_TTL_SECONDS", 0)))
    if ttl_seconds <= 0:
        return
    cache.set(_READY_CACHE_KEY, {"payload": payload, "status_code": status_code}, timeout=ttl_seconds)


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

    cached = _load_cached_ready_payload()
    if cached is not None:
        payload, status_code = cached
        return JsonResponse(payload, status=status_code)

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

    websocket_routing_ok, websocket_routing_error = get_websocket_routing_status()
    if not websocket_routing_ok:
        checks["websocket_routing"] = False
        if settings.DEBUG and websocket_routing_error:
            errors["websocket_routing"] = websocket_routing_error

    ok = all(checks.values())
    payload: dict[str, object] = {"status": "ok" if ok else "error", "checks": checks}
    if errors:
        payload["errors"] = errors

    if _should_include_health_details():
        degradation = get_degradation_counts()
        if degradation:
            payload["degradation_counts"] = degradation

        task_metrics = get_task_metrics()
        if task_metrics:
            payload["task_metrics"] = task_metrics

        degraded_counters = {c: get_degraded_counter(c) for c in _DEGRADED_COMPONENTS}
        nonzero_degraded = {c: v for c, v in degraded_counters.items() if v > 0}
        if nonzero_degraded:
            payload["degraded_counters"] = nonzero_degraded

    status_code = 200 if ok else 503
    _store_cached_ready_payload(payload, status_code)
    return JsonResponse(payload, status=status_code)
