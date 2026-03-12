from guests import growth_rules
from guests import models as guest_models
from guests.utils import attribute_growth


def test_normalize_guest_growth_rules_merges_and_clamps_values():
    loaded = growth_rules.normalize_guest_growth_rules(
        {
            "rarity_hp_profiles": {
                "blue": {"base": "650"},
                "orange": {"base": -20},
            },
            "rarity_skill_point_gains": {
                "purple": "3",
            },
            "rarity_attribute_growth_range": {
                "green": ["4", "8"],
                "red": {"min": 9, "max": 7},
            },
            "archetype_attribute_weights": {
                "military": {"force": "50", "intellect": 10, "defense": 20, "agility": 20},
                "civil": {"force": 0, "intellect": 0, "defense": 0, "agility": 0},
            },
        }
    )

    assert loaded["rarity_hp_profiles"]["blue"]["base"] == 650
    assert loaded["rarity_hp_profiles"]["orange"]["base"] == 0
    assert loaded["rarity_skill_point_gains"]["purple"] == 3
    assert loaded["rarity_attribute_growth_range"]["green"] == (4, 8)
    assert loaded["rarity_attribute_growth_range"]["red"] == (9, 9)
    assert loaded["archetype_attribute_weights"]["military"]["force"] == 50
    assert (
        loaded["archetype_attribute_weights"]["civil"]
        == growth_rules.DEFAULT_GUEST_GROWTH_RULES["archetype_attribute_weights"]["civil"]
    )


def test_clear_guest_growth_rules_cache_refreshes_exported_constants(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(
            "guests.growth_rules.load_yaml_data",
            lambda *args, **kwargs: {
                "rarity_hp_profiles": {"blue": {"base": 777}},
                "rarity_attribute_growth_range": {"blue": [7, 12]},
                "archetype_attribute_weights": {
                    "military": {"force": 55, "intellect": 10, "defense": 20, "agility": 15}
                },
            },
        )
        growth_rules.clear_guest_growth_rules_cache()

        assert growth_rules.RARITY_HP_PROFILES["blue"]["base"] == 777
        assert guest_models.RARITY_HP_PROFILES["blue"]["base"] == 777
        assert growth_rules.RARITY_ATTRIBUTE_GROWTH_RANGE["blue"] == (7, 12)
        assert attribute_growth.RARITY_ATTRIBUTE_GROWTH_RANGE["blue"] == (7, 12)
        assert attribute_growth.MILITARY_ATTRIBUTE_WEIGHTS["force"] == 55

    growth_rules.clear_guest_growth_rules_cache()
