from __future__ import annotations

from typing import Any

from gameplay.constants import PVPConstants, get_raid_capture_guest_rate
from gameplay.services.jail import list_held_prisoners, list_oath_bonds
from guests.query_utils import guest_template_rarity_rank_case


def get_jail_page_context(manor: Any) -> dict[str, Any]:
    prisoners = list_held_prisoners(manor)
    return {
        "jail_capacity": int(getattr(manor, "jail_capacity", 0) or 0),
        "prisoners": prisoners,
        "capture_rate_percent": int(round(get_raid_capture_guest_rate() * 100)),
        "recruit_loyalty_threshold": int(PVPConstants.JAIL_RECRUIT_LOYALTY_THRESHOLD),
        "recruit_cost_gold_bar": int(PVPConstants.JAIL_RECRUIT_GOLD_BAR_COST),
    }


def get_oath_grove_page_context(manor: Any) -> dict[str, Any]:
    bonds = list_oath_bonds(manor)
    oathed_ids = {bond.guest_id for bond in bonds}
    available_guests = (
        manor.guests.select_related("template")
        .exclude(id__in=oathed_ids)
        .annotate(_template_rarity_rank=guest_template_rarity_rank_case("template__rarity"))
        .order_by("-_template_rarity_rank", "-level", "id")
    )
    return {
        "oath_capacity": int(getattr(manor, "oath_capacity", 0) or 0),
        "bonds": bonds,
        "available_guests": list(available_guests)[:50],
    }
