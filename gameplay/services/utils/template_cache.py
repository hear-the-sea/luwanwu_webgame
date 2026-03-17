from __future__ import annotations


def clear_building_template_cache() -> None:
    from ...utils.template_loader import clear_building_types_cache
    from ..buildings import clear_building_cache

    clear_building_cache()
    clear_building_types_cache()


def clear_technology_template_cache() -> None:
    from ..technology import clear_technology_cache

    clear_technology_cache()


def clear_troop_template_caches() -> None:
    from battle.troops import invalidate_troop_templates_cache

    from ..recruitment.recruitment import clear_troop_cache

    invalidate_troop_templates_cache()
    clear_troop_cache()


def clear_all_template_caches() -> None:
    clear_building_template_cache()
    clear_technology_template_cache()
    clear_troop_template_caches()
