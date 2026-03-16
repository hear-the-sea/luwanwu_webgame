from __future__ import annotations


def cleanup_local_fallback_cache(
    local_refresh_fallback: dict[int, float],
    *,
    max_size: int,
    cleanup_batch: int,
    evict_count: int,
    now_monotonic: float,
    stale_threshold: float,
) -> None:
    stale_before = now_monotonic - stale_threshold

    stale_keys = [key for key, ts in local_refresh_fallback.items() if ts < stale_before]
    for key in stale_keys[:cleanup_batch]:
        local_refresh_fallback.pop(key, None)

    if len(local_refresh_fallback) > max_size:
        sorted_items = sorted(local_refresh_fallback.items(), key=lambda item: item[1])
        for key, _ in sorted_items[:evict_count]:
            local_refresh_fallback.pop(key, None)


def should_skip_refresh_by_local_fallback(
    local_refresh_fallback: dict[int, float],
    *,
    state_lock,
    max_size: int,
    cleanup_batch: int,
    evict_count: int,
    manor_id: int,
    min_interval: int,
    monotonic_func,
) -> bool:
    if manor_id <= 0 or min_interval <= 0:
        return False

    now_monotonic = monotonic_func()
    stale_threshold = max(min_interval * 2, 60)

    with state_lock:
        last_refresh = local_refresh_fallback.get(manor_id)
        if last_refresh is not None and now_monotonic - last_refresh < min_interval:
            return True

        local_refresh_fallback[manor_id] = now_monotonic
        if len(local_refresh_fallback) > max_size:
            cleanup_local_fallback_cache(
                local_refresh_fallback,
                max_size=max_size,
                cleanup_batch=cleanup_batch,
                evict_count=evict_count,
                now_monotonic=now_monotonic,
                stale_threshold=stale_threshold,
            )

    return False


def has_due_manor_refresh_work(*, mission_run_model, manor_id: int, now, logger) -> bool:
    if manor_id <= 0:
        return False
    try:
        return mission_run_model.objects.filter(
            manor_id=manor_id,
            status=mission_run_model.Status.ACTIVE,
            return_at__isnull=False,
            return_at__lte=now,
        ).exists()
    except Exception:
        logger.warning("due manor refresh work check failed: manor_id=%s", manor_id, exc_info=True)
        return False


def refresh_manor_state(
    manor,
    *,
    prefer_async: bool,
    settings_obj,
    cache_backend,
    logger,
    timezone_module,
    finalize_upgrades_func,
    has_due_manor_refresh_work_func,
    should_skip_refresh_by_local_fallback_func,
    sync_resource_production_func,
    refresh_mission_runs_func,
) -> None:
    finalize_upgrades_func(manor)

    min_interval = getattr(settings_obj, "MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS", 0)
    if min_interval > 0:
        now = timezone_module.now()
        cache_key = f"manor:refresh:{manor.pk}"
        try:
            if not cache_backend.add(cache_key, "1", timeout=min_interval):
                if not has_due_manor_refresh_work_func(manor.pk, now=now):
                    return
        except Exception as exc:
            logger.warning("缓存操作失败，降级为本地节流: %s", exc, exc_info=True)
            if should_skip_refresh_by_local_fallback_func(manor.pk, min_interval):
                if not has_due_manor_refresh_work_func(manor.pk, now=now):
                    return

    sync_resource_production_func(manor)
    if prefer_async:
        refresh_mission_runs_func(manor, prefer_async=True)
    else:
        refresh_mission_runs_func(manor)


__all__ = [
    "cleanup_local_fallback_cache",
    "has_due_manor_refresh_work",
    "refresh_manor_state",
    "should_skip_refresh_by_local_fallback",
]
