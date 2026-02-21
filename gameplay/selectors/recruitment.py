from __future__ import annotations

from guests.services import list_candidates, list_pools

from ..models import InventoryItem
from ..services import refresh_manor_state
from ..services.utils.query_optimization import optimize_guest_queryset


def get_recruitment_hall_context(manor, records_limit: int) -> dict:
    refresh_manor_state(manor)

    guests_list = list(optimize_guest_queryset(manor.guests.all()))

    magnifying_glass_items = manor.inventory_items.filter(
        template__key="fangdajing",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).select_related("template")

    return {
        "manor": manor,
        "pools": list_pools(core_only=True),
        "candidates": list_candidates(manor),
        "records": manor.recruit_records.select_related("guest", "pool")[:records_limit],
        "guests": guests_list,
        "capacity": (len(guests_list), manor.guest_capacity),
        "retainer_capacity": (manor.retainer_count, manor.retainer_capacity),
        "available_gears": manor.gears.filter(guest__isnull=True).select_related("template"),
        "magnifying_glass_items": list(magnifying_glass_items),
    }
