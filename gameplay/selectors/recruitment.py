from __future__ import annotations

from common.constants.resources import ResourceType
from guests.services import (
    get_active_guest_recruitment,
    get_pool_recruitment_duration_seconds,
    list_candidates,
    list_pools,
    refresh_guest_recruitments,
)

from ..models import InventoryItem
from ..services import refresh_manor_state
from ..services.utils.query_optimization import optimize_guest_queryset


def _format_duration_cn(seconds: int) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if sec or not parts:
        parts.append(f"{sec}秒")
    return "".join(parts)


def get_recruitment_hall_context(manor, records_limit: int) -> dict:
    refresh_manor_state(manor)
    refresh_guest_recruitments(manor)

    guests_list = list(optimize_guest_queryset(manor.guests.all()))
    pools = list(list_pools(core_only=True))
    for pool in pools:
        duration_seconds = get_pool_recruitment_duration_seconds(pool)
        setattr(pool, "recruit_duration_seconds", duration_seconds)
        setattr(pool, "recruit_duration_display", _format_duration_cn(duration_seconds))
    active_recruitment = get_active_guest_recruitment(manor)

    magnifying_glass_items = manor.inventory_items.filter(
        template__key="fangdajing",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).select_related("template")

    return {
        "manor": manor,
        "resource_labels": dict(ResourceType.choices),
        "pools": pools,
        "candidates": list_candidates(manor),
        "active_recruitment": active_recruitment,
        "records": manor.recruit_records.select_related("guest", "pool")[:records_limit],
        "guests": guests_list,
        "capacity": (len(guests_list), manor.guest_capacity),
        "retainer_capacity": (manor.retainer_count, manor.retainer_capacity),
        "available_gears": manor.gears.filter(guest__isnull=True).select_related("template"),
        "magnifying_glass_items": list(magnifying_glass_items),
    }
