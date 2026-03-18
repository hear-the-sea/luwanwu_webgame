from __future__ import annotations

from typing import Callable, Iterable


def get_ready_cache_ttl(settings_obj: object) -> int:
    """Return the configured ready-check cache TTL in seconds."""
    return max(0, int(getattr(settings_obj, "HEALTH_CHECK_CACHE_TTL_SECONDS", 0)))


def load_cached_ready_payload(
    *,
    cache_backend: object,
    cache_key: str,
    ttl_seconds: int,
) -> tuple[dict[str, object], int] | None:
    """Load a cached ready payload when response caching is enabled."""
    if ttl_seconds <= 0:
        return None

    cached = cache_backend.get(cache_key)
    if not isinstance(cached, dict):
        return None

    payload = cached.get("payload")
    status_code = cached.get("status_code")
    if not isinstance(payload, dict) or not isinstance(status_code, int):
        return None
    return payload, status_code


def store_cached_ready_payload(
    *,
    cache_backend: object,
    cache_key: str,
    payload: dict[str, object],
    status_code: int,
    ttl_seconds: int,
) -> None:
    """Store a ready payload when response caching is enabled."""
    if ttl_seconds <= 0:
        return
    cache_backend.set(cache_key, {"payload": payload, "status_code": status_code}, timeout=ttl_seconds)


def apply_check_result(
    *,
    checks: dict[str, bool],
    errors: dict[str, str],
    check_name: str,
    ok: bool,
    error: str | None,
) -> None:
    """Persist the result of a health check into aggregate response state."""
    checks[check_name] = ok
    if error:
        errors[check_name] = error


def build_health_details(
    *,
    degraded_components: Iterable[str],
    degradation_reader: Callable[[], dict[str, int]],
    task_metrics_reader: Callable[[], dict[str, dict[str, int]]],
    degraded_counter_reader: Callable[[str], int],
) -> dict[str, object]:
    """Build optional health detail sections, omitting empty sections."""
    details: dict[str, object] = {}

    degradation = degradation_reader()
    if degradation:
        details["degradation_counts"] = degradation

    task_metrics = task_metrics_reader()
    if task_metrics:
        details["task_metrics"] = task_metrics

    degraded_counters = {component: degraded_counter_reader(component) for component in degraded_components}
    nonzero_degraded = {component: count for component, count in degraded_counters.items() if count > 0}
    if nonzero_degraded:
        details["degraded_counters"] = nonzero_degraded

    return details
