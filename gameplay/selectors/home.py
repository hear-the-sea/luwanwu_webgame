from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.utils import safe_int
from guests.models import RARITY_SALARY, GuestStatus

from ..models import MissionRun, ResourceType
from ..services import can_retreat, get_technology_template, refresh_manor_state, refresh_technology_upgrades
from ..services.utils.cache import CacheKeys
from ..services.utils.query_optimization import optimize_guest_queryset


def _normalize_hourly_rates(hourly_rates) -> dict[str, int]:
    if not isinstance(hourly_rates, dict):
        return {}

    normalized: dict[str, int] = {}
    for key, value in hourly_rates.items():
        if not isinstance(key, str) or not key:
            continue
        normalized[key] = safe_int(value, default=0, min_val=0) or 0
    return normalized


def get_home_context(manor) -> dict:
    refresh_manor_state(manor, prefer_async=True)
    refresh_technology_upgrades(manor)

    resources = [
        ("grain", "粮食", manor.grain),
        ("silver", "银两", manor.silver),
        ("retainer", "家丁", f"{manor.retainer_count} / {manor.retainer_capacity}"),
    ]

    guests = list(optimize_guest_queryset(manor.guests.all()).order_by("template__name"))
    guest_status_display = dict(GuestStatus.choices)
    for guest in guests:
        guest.status_display = guest_status_display.get(guest.status, guest.status)

    runs = list(
        manor.mission_runs.select_related("mission")
        .prefetch_related("guests__template")
        .filter(status=MissionRun.Status.ACTIVE, return_at__isnull=False)
    )
    now = timezone.now()
    for run in runs:
        run.can_retreat = can_retreat(run, now=now)

    upgrading_buildings = list(
        manor.buildings.select_related("building_type")
        .filter(is_upgrading=True, upgrade_complete_at__isnull=False)
        .order_by("upgrade_complete_at")
    )

    upgrading_techs = list(
        manor.technologies.filter(is_upgrading=True, upgrade_complete_at__isnull=False).order_by("upgrade_complete_at")
    )
    for tech in upgrading_techs:
        tpl = get_technology_template(tech.tech_key) or {}
        tech.display_name = tpl.get("name", tech.tech_key)

    total_guest_salary = sum(RARITY_SALARY.get(g.rarity, 1000) for g in guests)

    from ..utils.resource_calculator import get_hourly_rates, get_personnel_grain_cost_per_hour

    cache_key = CacheKeys.home_hourly_rates(manor.pk)
    hourly_rates = cache.get(cache_key)
    if hourly_rates is None:
        hourly_rates = get_hourly_rates(manor)
        cache.set(cache_key, hourly_rates, timeout=settings.HOME_STATS_CACHE_TTL_SECONDS)
    hourly_rates = _normalize_hourly_rates(hourly_rates)
    resource_labels = dict(ResourceType.choices)
    building_income = []
    for res_type, rate in hourly_rates.items():
        if rate > 0:
            label = resource_labels.get(res_type, res_type)
            building_income.append({"resource": res_type, "label": label, "rate": rate})

    player_troops = list(
        manor.troops.select_related("troop_template").filter(count__gt=0).order_by("troop_template__priority")
    )

    from ..services.raid import (
        get_active_raids,
        get_active_scouts,
        get_incoming_raids,
        refresh_raid_runs,
        refresh_scout_records,
    )

    refresh_scout_records(manor, prefer_async=True)
    refresh_raid_runs(manor, prefer_async=True)

    return {
        "manor": manor,
        "resources": resources,
        "resource_labels": resource_labels,
        "guests": guests,
        "guest_count": len(guests),
        "active_runs": runs,
        "upgrading_buildings": upgrading_buildings,
        "upgrading_technologies": upgrading_techs,
        "total_guest_salary": total_guest_salary,
        "building_income": building_income,
        "grain_production": hourly_rates.get("grain", 0),
        "personnel_grain_cost": get_personnel_grain_cost_per_hour(manor),
        "player_troops": player_troops,
        "active_scouts": get_active_scouts(manor),
        "active_raids": get_active_raids(manor),
        "incoming_raids": get_incoming_raids(manor),
    }
