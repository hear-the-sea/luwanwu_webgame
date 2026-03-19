from __future__ import annotations

import logging
from typing import Any

from django.core.paginator import Paginator
from django.http import HttpRequest

from gameplay.constants import UIConstants
from gameplay.services.buildings import forge as forge_service
from gameplay.services.buildings.ranch import (
    get_active_livestock_productions,
    get_livestock_options,
    get_max_livestock_quantity,
    get_ranch_speed_bonus,
    has_active_livestock_production,
)
from gameplay.services.buildings.smithy import (
    get_active_smelting_productions,
    get_max_smelting_quantity,
    get_metal_options,
    get_smithy_speed_bonus,
    has_active_smelting_production,
)
from gameplay.services.buildings.stable import (
    get_active_productions,
    get_horse_options,
    get_max_production_quantity,
    get_stable_speed_bonus,
    has_active_production,
)
from gameplay.services.resources import project_resource_production_for_read
from gameplay.services.technology import get_player_technology_level
from gameplay.views.production_helpers import (
    annotate_blueprint_synthesis_options,
    build_categories_with_all,
    get_filtered_equipment_options,
    normalize_forge_category,
    resolve_decompose_category,
)
from gameplay.views.read_helpers import get_prepared_manor_for_read

logger = logging.getLogger(__name__)


def _prepare_production_manor(request: HttpRequest, *, source: str):
    return get_prepared_manor_for_read(
        request,
        project_fn=project_resource_production_for_read,
        logger=logger,
        source=source,
    )


def build_stable_page_context(request: HttpRequest) -> dict[str, Any]:
    manor = _prepare_production_manor(request, source="stable_view")
    speed_bonus = get_stable_speed_bonus(manor)
    return {
        "manor": manor,
        "horse_options": get_horse_options(manor),
        "active_productions": get_active_productions(manor),
        "speed_bonus": speed_bonus,
        "speed_bonus_percent": int(speed_bonus * 100),
        "horsemanship_level": get_player_technology_level(manor, "horsemanship"),
        "max_production_quantity": get_max_production_quantity(manor),
        "is_producing": has_active_production(manor),
    }


def build_ranch_page_context(request: HttpRequest) -> dict[str, Any]:
    manor = _prepare_production_manor(request, source="ranch_view")
    speed_bonus = get_ranch_speed_bonus(manor)
    return {
        "manor": manor,
        "livestock_options": get_livestock_options(manor),
        "active_productions": get_active_livestock_productions(manor),
        "speed_bonus": speed_bonus,
        "speed_bonus_percent": int(speed_bonus * 100),
        "animal_husbandry_level": get_player_technology_level(manor, "animal_husbandry"),
        "max_livestock_quantity": get_max_livestock_quantity(manor),
        "is_producing": has_active_livestock_production(manor),
    }


def build_smithy_page_context(request: HttpRequest) -> dict[str, Any]:
    manor = _prepare_production_manor(request, source="smithy_view")
    speed_bonus = get_smithy_speed_bonus(manor)
    return {
        "manor": manor,
        "metal_options": get_metal_options(manor),
        "active_productions": get_active_smelting_productions(manor),
        "speed_bonus": speed_bonus,
        "speed_bonus_percent": int(speed_bonus * 100),
        "smelting_level": get_player_technology_level(manor, "smelting"),
        "max_smelting_quantity": get_max_smelting_quantity(manor),
        "is_producing": has_active_smelting_production(manor),
    }


def _normalize_forge_mode(raw_mode: str | None, *, default: str = "synthesize") -> str:
    mode = (raw_mode or default).strip()
    if mode not in {"synthesize", "decompose"}:
        return default
    return mode


def build_forge_page_context(
    request: HttpRequest,
    *,
    items_per_page: int = UIConstants.FORGE_ITEMS_PER_PAGE,
    decompose_items_per_page: int = 9,
) -> dict[str, Any]:
    manor = _prepare_production_manor(request, source="forge_view")
    forging_level = get_player_technology_level(manor, "forging")
    max_quantity = forge_service.get_max_forging_quantity(manor)
    is_forging = forge_service.has_active_forging(manor)
    current_mode = _normalize_forge_mode(request.GET.get("mode"), default="synthesize")

    active_categories = forge_service.DECOMPOSE_CATEGORIES
    current_category = normalize_forge_category(
        request.GET.get("category", "all"),
        active_categories=active_categories,
        weapon_categories=forge_service.DECOMPOSE_WEAPON_CATEGORIES,
    )
    equipment_list = get_filtered_equipment_options(
        manor=manor,
        current_category=current_category,
        weapon_categories=forge_service.DECOMPOSE_WEAPON_CATEGORIES,
        get_equipment_options=forge_service.get_equipment_options,
    )
    paginator = Paginator(equipment_list, items_per_page)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    blueprint_synthesis_options = annotate_blueprint_synthesis_options(
        forge_service.get_blueprint_synthesis_options(manor),
        active_categories=active_categories,
        current_category=current_category,
        infer_equipment_category=forge_service.infer_equipment_category,
        to_decompose_category=forge_service.to_decompose_category,
    )

    decompose_category = resolve_decompose_category(current_category)
    decomposable_equipment = forge_service.get_decomposable_equipment_options(manor, category=decompose_category)
    decompose_paginator = Paginator(decomposable_equipment, decompose_items_per_page)
    decompose_page_obj = decompose_paginator.get_page(page_number)
    speed_bonus = forge_service.get_forge_speed_bonus(manor)

    return {
        "manor": manor,
        "current_mode": current_mode,
        "equipment_categories": build_categories_with_all(active_categories),
        "current_category": current_category,
        "equipment_list": page_obj,
        "page_obj": page_obj,
        "decompose_page_obj": decompose_page_obj,
        "active_forgings": forge_service.get_active_forgings(manor),
        "blueprint_synthesis_options": blueprint_synthesis_options,
        "decomposable_equipment": decompose_page_obj,
        "speed_bonus": speed_bonus,
        "speed_bonus_percent": int(speed_bonus * 100),
        "forging_level": forging_level,
        "max_forging_quantity": max_quantity,
        "is_forging": is_forging,
    }
