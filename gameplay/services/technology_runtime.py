from __future__ import annotations

from typing import Callable

from django.db.models import F


def should_skip_tech_refresh_by_local_fallback(
    local_refresh_state: dict[int, float],
    *,
    state_lock,
    max_size: int,
    manor_id: int,
    min_interval: int,
    monotonic_func: Callable[[], float],
) -> bool:
    if manor_id <= 0 or min_interval <= 0:
        return False

    now_monotonic = monotonic_func()
    stale_before = now_monotonic - max(min_interval * 2, 60)

    with state_lock:
        last_refresh = local_refresh_state.get(manor_id)
        if last_refresh is not None and now_monotonic - last_refresh < min_interval:
            return True

        local_refresh_state[manor_id] = now_monotonic
        if len(local_refresh_state) > max_size:
            stale_keys = [key for key, ts in local_refresh_state.items() if ts < stale_before]
            for key in stale_keys[:1000]:
                local_refresh_state.pop(key, None)
            if len(local_refresh_state) > max_size:
                for key, _ in sorted(local_refresh_state.items(), key=lambda item: item[1])[:500]:
                    local_refresh_state.pop(key, None)
    return False


def upgrade_technology(
    manor,
    tech_key: str,
    *,
    get_technology_template_func,
    calculate_upgrade_cost_func,
    max_concurrent_tech_upgrades: int,
    schedule_technology_completion_func,
    build_technology_upgrade_response_func,
    transaction_module,
    technology_not_found_error_cls,
    technology_upgrade_in_progress_error_cls,
    technology_max_level_error_cls,
    technology_concurrent_upgrade_limit_error_cls,
    insufficient_resource_error_cls,
):
    from datetime import timedelta

    from django.utils import timezone

    from ..models import Manor, PlayerTechnology
    from .manor.prestige import add_prestige_silver_locked
    from .resources import spend_resources_locked

    template = get_technology_template_func(tech_key)
    if not template:
        raise technology_not_found_error_cls(tech_key)

    max_level = template.get("max_level", 10)

    with transaction_module.atomic():
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
        tech, _created = PlayerTechnology.objects.get_or_create(
            manor=locked_manor, tech_key=tech_key, defaults={"level": 0}
        )

        if tech.is_upgrading:
            raise technology_upgrade_in_progress_error_cls(tech_key, template["name"])
        if tech.level >= max_level:
            raise technology_max_level_error_cls(tech_key, template["name"], max_level)

        upgrading_count = PlayerTechnology.objects.filter(manor=locked_manor, is_upgrading=True).count()
        if upgrading_count >= max_concurrent_tech_upgrades:
            raise technology_concurrent_upgrade_limit_error_cls(max_concurrent_tech_upgrades)

        cost = calculate_upgrade_cost_func(tech_key, tech.level)
        try:
            spend_resources_locked(
                locked_manor,
                {"silver": cost},
                reason="tech_upgrade",
                note=f"升级{template['name']}",
            )
        except ValueError as exc:
            raise insufficient_resource_error_cls("silver", cost, locked_manor.silver) from exc

        add_prestige_silver_locked(locked_manor, cost)

        duration = tech.upgrade_duration()
        tech.is_upgrading = True
        tech.upgrade_complete_at = timezone.now() + timedelta(seconds=duration)
        tech.save(update_fields=["is_upgrading", "upgrade_complete_at"])

        schedule_technology_completion_func(tech, duration)

    return build_technology_upgrade_response_func(template_name=template["name"], duration=duration)


def finalize_technology_upgrade(
    tech,
    *,
    get_technology_template_func,
    resolve_technology_name_func,
    send_technology_completion_notification_func,
    notify_user_func,
    invalidate_home_stats_cache_func,
    logger,
    send_notification: bool = False,
) -> bool:
    from django.utils import timezone

    if not getattr(tech, "pk", None):
        return False
    now = timezone.now()
    updated = tech.__class__.objects.filter(
        pk=tech.pk,
        is_upgrading=True,
        upgrade_complete_at__isnull=False,
        upgrade_complete_at__lte=now,
    ).update(
        level=F("level") + 1,
        is_upgrading=False,
        upgrade_complete_at=None,
        updated_at=now,
    )
    if updated != 1:
        return False

    tech = tech.__class__.objects.select_related("manor").get(pk=tech.pk)
    template = get_technology_template_func(tech.tech_key)
    tech_name = resolve_technology_name_func(template, tech.tech_key)

    if send_notification:
        send_technology_completion_notification_func(
            tech=tech,
            tech_name=tech_name,
            logger=logger,
            notify_user_func=notify_user_func,
        )

    invalidate_home_stats_cache_func(tech.manor_id)
    return True


def refresh_technology_upgrades(
    manor,
    *,
    settings_obj,
    cache_backend,
    logger,
    should_skip_tech_refresh_by_local_fallback_func,
    finalize_technology_upgrade_func,
) -> int:
    from django.utils import timezone

    min_interval = getattr(settings_obj, "MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS", 0)
    if min_interval > 0 and getattr(manor, "pk", None):
        cache_key = f"tech:refresh:{manor.pk}"
        try:
            if not cache_backend.add(cache_key, "1", timeout=min_interval):
                return 0
        except Exception as exc:
            logger.warning("Technology refresh cache unavailable, fallback to local throttle: %s", exc, exc_info=True)
            if should_skip_tech_refresh_by_local_fallback_func(int(manor.pk), min_interval):
                return 0

    completed = 0
    upgrading_techs = list(manor.technologies.filter(is_upgrading=True, upgrade_complete_at__lte=timezone.now()))
    for tech in upgrading_techs:
        if finalize_technology_upgrade_func(tech, send_notification=True):
            completed += 1

    return completed


__all__ = [
    "finalize_technology_upgrade",
    "refresh_technology_upgrades",
    "should_skip_tech_refresh_by_local_fallback",
    "upgrade_technology",
]
