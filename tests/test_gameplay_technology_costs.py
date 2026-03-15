from __future__ import annotations

from gameplay.constants import BUILDING_MAX_LEVELS, BuildingKeys
from gameplay.services import technology as tech_service
from gameplay.services.manor.core import calculate_building_capacity


def test_calculate_upgrade_cost_uses_template_cost_growth(monkeypatch):
    monkeypatch.setattr(
        tech_service,
        "get_technology_template",
        lambda key: {"base_cost": 100, "cost_growth": 1.2} if key == "custom" else {"base_cost": 100},
    )

    assert tech_service.calculate_upgrade_cost("custom", 2) == int(100 * (1.2**2))
    assert tech_service.calculate_upgrade_cost("default", 2) == int(100 * (1.5**2))


def test_all_technology_upgrade_costs_fit_within_max_silver_capacity():
    tech_service.clear_technology_cache()
    max_silver_capacity = calculate_building_capacity(
        BUILDING_MAX_LEVELS[BuildingKeys.SILVER_VAULT],
        is_silver_vault=True,
    )
    violations: list[str] = []

    for template in tech_service.load_technology_templates().get("technologies", []) or []:
        if not isinstance(template, dict):
            continue
        tech_key = str(template.get("key") or "").strip()
        if not tech_key:
            continue
        max_level = max(0, int(template.get("max_level", 0) or 0))
        for current_level in range(max_level):
            cost = tech_service.calculate_upgrade_cost(tech_key, current_level)
            if cost > max_silver_capacity:
                violations.append(f"{tech_key} {current_level}->{current_level + 1}: {cost}")

    tech_service.clear_technology_cache()
    assert violations == []
