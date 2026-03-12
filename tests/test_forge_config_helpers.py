from gameplay.services.buildings.forge_config_helpers import (
    DEFAULT_FORGE_BLUEPRINT_CONFIG,
    DEFAULT_FORGE_DECOMPOSE_CONFIG,
    _normalize_blueprint_config,
    _normalize_decompose_config,
    _normalize_quantity_range,
)


def test_normalize_quantity_range_clamps_and_orders_values():
    assert _normalize_quantity_range(["-2", "5"], [1, 3]) == [0, 5]
    assert _normalize_quantity_range([4, 1], [1, 3]) == [4, 4]
    assert _normalize_quantity_range("invalid", [1, 3]) == [1, 3]


def test_normalize_decompose_config_uses_defaults_for_invalid_root():
    assert _normalize_decompose_config(["invalid-root"]) == DEFAULT_FORGE_DECOMPOSE_CONFIG


def test_normalize_decompose_config_merges_probabilities_and_filters_supported_rarities():
    config = _normalize_decompose_config(
        {
            "supported_rarities": ["green", "mystery"],
            "base_materials": {
                "green": {"tong": [1, 2]},
            },
            "chance_rewards": {
                "green": {"wood_essence": 1.2, "new_reward": -0.5},
            },
        }
    )

    assert config["supported_rarities"] == ["green"]
    assert config["base_materials"]["green"]["tong"] == [1, 2]
    assert config["chance_rewards"]["green"]["wood_essence"] == 1.0
    assert config["chance_rewards"]["green"]["new_reward"] == 0.0


def test_normalize_blueprint_config_discards_invalid_entries():
    config = _normalize_blueprint_config(
        {
            "recipes": [
                {"blueprint_key": "bp_ok", "result_item_key": "equip_ok", "required_forging": "3"},
                {"blueprint_key": "", "result_item_key": "equip_missing"},
                {"blueprint_key": "bp_missing_result"},
                "invalid-row",
            ]
        }
    )

    assert config == {
        "recipes": [
            {
                "blueprint_key": "bp_ok",
                "result_item_key": "equip_ok",
                "required_forging": 3,
                "quantity_out": 1,
                "costs": {},
                "description": "",
            }
        ]
    }
    assert DEFAULT_FORGE_BLUEPRINT_CONFIG == {"recipes": []}
