from __future__ import annotations

from unittest.mock import mock_open

from gameplay.services import technology as tech_service


def test_get_tech_bonus_from_levels_tolerates_invalid_level_and_template_rows(monkeypatch):
    monkeypatch.setattr(
        tech_service,
        "load_technology_templates",
        lambda: {
            "technologies": [
                "bad-row",
                {"effect_type": "troop_attack"},  # missing key
                {"key": "atk_1", "effect_type": "troop_attack", "effect_per_level": "bad"},
            ]
        },
    )

    bonus = tech_service.get_tech_bonus_from_levels({"atk_1": "bad"}, "troop_attack")
    assert bonus == 0.0


def test_build_uniform_tech_levels_skips_invalid_rows(monkeypatch):
    monkeypatch.setattr(
        tech_service,
        "load_technology_templates",
        lambda: {
            "technologies": [
                {"key": "t1", "max_level": "3"},
                {"max_level": 5},
                {"key": "t2", "max_level": "bad"},
                "not-a-dict",
            ]
        },
    )

    resolved = tech_service.build_uniform_tech_levels(2)
    assert resolved == {"t1": 2, "t2": 2}


def test_resolve_enemy_tech_levels_tolerates_invalid_values(monkeypatch):
    monkeypatch.setattr(
        tech_service,
        "load_technology_templates",
        lambda: {
            "technologies": [
                {"key": "t1", "max_level": 5},
                {"key": "t2", "max_level": 5},
            ]
        },
    )

    resolved = tech_service.resolve_enemy_tech_levels(
        {
            "level": "bad",
            "levels": {"t1": "7", "t2": "oops", "": "3", "t3": -2},
        }
    )
    assert resolved["t1"] == 7
    assert resolved["t2"] == 0
    assert resolved["t3"] == 0
    assert "" not in resolved


def test_resource_production_bonus_ignores_bad_effect_value(monkeypatch):
    monkeypatch.setattr(
        tech_service,
        "load_technology_templates",
        lambda: {
            "technologies": [
                {
                    "key": "grain_1",
                    "effect_type": "resource_production",
                    "resource_type": "grain",
                    "effect_per_level": "bad",
                }
            ]
        },
    )

    bonus = tech_service.get_resource_production_bonus_from_levels({"grain_1": 2}, "grain")
    assert bonus == 0.1


def test_get_categories_and_troop_classes_return_safe_defaults(monkeypatch):
    monkeypatch.setattr(
        tech_service,
        "load_technology_templates",
        lambda: {
            "categories": "bad-type",
            "troop_classes": "bad-type",
        },
    )

    assert tech_service.get_categories() == []
    assert tech_service.get_troop_classes() == {}


def test_load_technology_templates_returns_empty_when_yaml_root_not_mapping(monkeypatch):
    tech_service.clear_technology_cache()
    monkeypatch.setattr("builtins.open", mock_open(read_data="[]"))
    monkeypatch.setattr(tech_service.yaml, "safe_load", lambda _stream: ["invalid-root"])

    data = tech_service.load_technology_templates()
    assert data == {}

    tech_service.clear_technology_cache()


def test_get_guest_stat_bonuses_tolerates_invalid_guest_bonus():
    bonuses = tech_service.get_guest_stat_bonuses({"guest_bonus": "bad-value"})
    assert bonuses == {"attack": 0.0, "defense": 0.0, "hp": 0.0, "agility": 0.0}
