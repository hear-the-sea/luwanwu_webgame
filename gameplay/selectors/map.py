from __future__ import annotations

from guests.models import GuestStatus

from ..services import refresh_manor_state
from ..services.raid import (
    can_attack_target,
    get_active_raids,
    get_active_scouts,
    get_incoming_raids,
    get_manor_public_info,
    get_protection_status,
    get_scout_count,
)
from ..services.recruitment import get_player_troops


def get_map_context(manor, selected_region: str, search_query: str) -> dict:
    refresh_manor_state(manor)

    return {
        "manor": manor,
        "selected_region": selected_region,
        "search_query": search_query,
        "protection_status": get_protection_status(manor),
        "active_raids": get_active_raids(manor),
        "active_scouts": get_active_scouts(manor),
        "incoming_raids": get_incoming_raids(manor),
        "scout_count": get_scout_count(manor),
        "player_troops": get_player_troops(manor),
    }


def get_raid_config_context(manor, target_manor) -> dict:
    refresh_manor_state(manor)
    target_info = get_manor_public_info(target_manor, viewer=manor)
    can_attack, attack_reason = can_attack_target(manor, target_manor)
    available_guests = list(
        manor.guests.filter(status=GuestStatus.IDLE).select_related("template").order_by("-level", "template__name")
    )
    return {
        "manor": manor,
        "target_manor": target_manor,
        "target_info": target_info,
        "can_attack": can_attack,
        "attack_reason": attack_reason,
        "available_guests": available_guests,
        "player_troops": get_player_troops(manor),
        "scout_count": get_scout_count(manor),
        "max_squad_size": manor.max_squad_size,
    }
