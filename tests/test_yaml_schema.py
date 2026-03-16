"""Tests for core.utils.yaml_schema validation module."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.utils.yaml_schema import (
    ValidationResult,
    validate_all_configs,
    validate_arena_rules,
    validate_building_templates,
    validate_forge_equipment,
    validate_guest_templates,
    validate_item_templates,
    validate_mission_templates,
    validate_shop_items,
    validate_trade_market_rules,
    validate_troop_templates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_valid(result: ValidationResult) -> None:
    __tracebackhide__ = True
    if not result.is_valid:
        lines = [str(e) for e in result.errors]
        pytest.fail(f"Expected valid, got {len(lines)} error(s):\n" + "\n".join(lines))


def _assert_has_error(result: ValidationResult, *, substring: str) -> None:
    __tracebackhide__ = True
    assert not result.is_valid, "Expected errors but result was valid"
    messages = [str(e) for e in result.errors]
    if not any(substring in msg for msg in messages):
        pytest.fail(f"No error containing '{substring}'. Errors:\n" + "\n".join(messages))


# ===========================================================================
# item_templates.yaml
# ===========================================================================


class TestItemTemplatesValidation:
    def test_valid_minimal(self):
        data = {"items": [{"key": "grain", "name": "Grain", "effect_type": "resource"}]}
        _assert_valid(validate_item_templates(data))

    def test_valid_full_entry(self):
        data = {
            "items": [
                {
                    "key": "grain",
                    "name": "Grain",
                    "effect_type": "resource",
                    "rarity": "black",
                    "tradeable": True,
                    "price": 10,
                    "storage_space": 1,
                    "is_usable": False,
                }
            ]
        }
        _assert_valid(validate_item_templates(data))

    def test_missing_root_key(self):
        result = validate_item_templates({})
        _assert_has_error(result, substring="missing required key 'items'")

    def test_non_dict_root(self):
        result = validate_item_templates([1, 2, 3])
        _assert_has_error(result, substring="expected a mapping at root level")

    def test_missing_required_fields(self):
        data = {"items": [{"key": "grain"}]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="missing required field 'name'")
        _assert_has_error(result, substring="missing required field 'effect_type'")

    def test_invalid_effect_type(self):
        data = {"items": [{"key": "x", "name": "X", "effect_type": "invalid"}]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="not in allowed set")

    def test_invalid_rarity(self):
        data = {"items": [{"key": "x", "name": "X", "effect_type": "tool", "rarity": "legendary"}]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="not in allowed set")

    def test_negative_price(self):
        data = {"items": [{"key": "x", "name": "X", "effect_type": "tool", "price": -10}]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="must be >= 0")

    def test_storage_space_zero(self):
        data = {"items": [{"key": "x", "name": "X", "effect_type": "tool", "storage_space": 0}]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="must be >= 1")

    def test_wrong_type_tradeable(self):
        data = {"items": [{"key": "x", "name": "X", "effect_type": "tool", "tradeable": "yes"}]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="expected bool")

    def test_duplicate_keys(self):
        data = {
            "items": [
                {"key": "dup", "name": "A", "effect_type": "tool"},
                {"key": "dup", "name": "B", "effect_type": "tool"},
            ]
        }
        result = validate_item_templates(data)
        _assert_has_error(result, substring="duplicate key 'dup'")

    def test_non_mapping_item(self):
        data = {"items": [{"key": "ok", "name": "Ok", "effect_type": "tool"}, "bad_entry"]}
        result = validate_item_templates(data)
        _assert_has_error(result, substring="expected a mapping")

    def test_all_equip_effect_types_accepted(self):
        equip_types = [
            "equip_helmet",
            "equip_armor",
            "equip_shoes",
            "equip_weapon",
            "equip_mount",
            "equip_ornament",
            "equip_device",
        ]
        items = [{"key": f"eq_{i}", "name": f"Eq{i}", "effect_type": et} for i, et in enumerate(equip_types)]
        _assert_valid(validate_item_templates({"items": items}))


# ===========================================================================
# building_templates.yaml
# ===========================================================================


class TestBuildingTemplatesValidation:
    def test_valid_minimal(self):
        data = {"buildings": [{"key": "farm", "name": "Farm", "category": "resource", "resource_type": "grain"}]}
        _assert_valid(validate_building_templates(data))

    def test_missing_buildings_key(self):
        result = validate_building_templates({})
        _assert_has_error(result, substring="missing required key 'buildings'")

    def test_invalid_category(self):
        data = {"buildings": [{"key": "b", "name": "B", "category": "invalid", "resource_type": "grain"}]}
        result = validate_building_templates(data)
        _assert_has_error(result, substring="not in allowed set")

    def test_invalid_resource_type(self):
        data = {"buildings": [{"key": "b", "name": "B", "category": "resource", "resource_type": "gold"}]}
        result = validate_building_templates(data)
        _assert_has_error(result, substring="not in allowed set")

    def test_negative_base_rate(self):
        data = {
            "buildings": [
                {
                    "key": "b",
                    "name": "B",
                    "category": "resource",
                    "resource_type": "grain",
                    "base_rate_per_hour": -5,
                }
            ]
        }
        result = validate_building_templates(data)
        _assert_has_error(result, substring="must be >= 0")

    def test_base_cost_non_dict(self):
        data = {
            "buildings": [
                {
                    "key": "b",
                    "name": "B",
                    "category": "resource",
                    "resource_type": "grain",
                    "base_cost": "invalid",
                }
            ]
        }
        result = validate_building_templates(data)
        _assert_has_error(result, substring="expected a mapping")

    def test_duplicate_keys(self):
        bld = {"key": "dup", "name": "D", "category": "resource", "resource_type": "grain"}
        data = {"buildings": [bld, dict(bld)]}
        result = validate_building_templates(data)
        _assert_has_error(result, substring="duplicate key 'dup'")

    def test_categories_validation(self):
        data = {
            "categories": [
                {"key": "resource", "name": "Resource"},
                {"name": "NoKey"},  # missing key
            ],
            "buildings": [],
        }
        result = validate_building_templates(data)
        _assert_has_error(result, substring="missing required field 'key'")


# ===========================================================================
# guest_templates.yaml
# ===========================================================================


class TestGuestTemplatesValidation:
    def test_valid_pools_and_profiles(self):
        data = {
            "pools": [
                {"key": "cunmu", "name": "Village", "cost": {"silver": 500}, "cooldown_seconds": 600, "draw_count": 1}
            ],
            "attribute_profiles": {
                "black": {
                    "military": {"force": 29, "intellect": 8},
                    "civil": {"force": 20, "intellect": 22},
                }
            },
        }
        _assert_valid(validate_guest_templates(data))

    def test_pool_missing_key(self):
        data = {"pools": [{"name": "Test"}]}
        result = validate_guest_templates(data)
        _assert_has_error(result, substring="missing required field 'key'")

    def test_negative_draw_count(self):
        data = {"pools": [{"key": "p", "name": "P", "draw_count": 0}]}
        result = validate_guest_templates(data)
        _assert_has_error(result, substring="must be >= 1")

    def test_unknown_rarity_in_profiles(self):
        data = {"attribute_profiles": {"legendary": {"military": {"force": 99}}}}
        result = validate_guest_templates(data)
        _assert_has_error(result, substring="unknown rarity")

    def test_unknown_archetype_in_profiles(self):
        data = {"attribute_profiles": {"black": {"wizard": {"force": 99}}}}
        result = validate_guest_templates(data)
        _assert_has_error(result, substring="unknown archetype")


# ===========================================================================
# troop_templates.yaml
# ===========================================================================


class TestTroopTemplatesValidation:
    def test_valid_minimal(self):
        data = {"troops": [{"key": "scout", "name": "Scout"}]}
        _assert_valid(validate_troop_templates(data))

    def test_missing_troops_key(self):
        result = validate_troop_templates({})
        _assert_has_error(result, substring="missing required key 'troops'")

    def test_missing_name(self):
        data = {"troops": [{"key": "scout"}]}
        result = validate_troop_templates(data)
        _assert_has_error(result, substring="missing required field 'name'")

    def test_recruit_not_mapping(self):
        data = {"troops": [{"key": "scout", "name": "Scout", "recruit": "bad"}]}
        result = validate_troop_templates(data)
        _assert_has_error(result, substring="expected a mapping")

    def test_recruit_equipment_not_list(self):
        data = {"troops": [{"key": "scout", "name": "Scout", "recruit": {"equipment": "not_a_list"}}]}
        result = validate_troop_templates(data)
        _assert_has_error(result, substring="expected a list")

    def test_duplicate_troop_keys(self):
        data = {"troops": [{"key": "dup", "name": "A"}, {"key": "dup", "name": "B"}]}
        result = validate_troop_templates(data)
        _assert_has_error(result, substring="duplicate key 'dup'")


# ===========================================================================
# mission_templates.yaml
# ===========================================================================


class TestMissionTemplatesValidation:
    def test_valid_minimal(self):
        data = {"missions": [{"key": "m1", "name": "Mission 1"}]}
        _assert_valid(validate_mission_templates(data))

    def test_missing_missions_key(self):
        result = validate_mission_templates({})
        _assert_has_error(result, substring="missing required key 'missions'")

    def test_invalid_daily_limit(self):
        data = {"missions": [{"key": "m", "name": "M", "daily_limit": 0}]}
        result = validate_mission_templates(data)
        _assert_has_error(result, substring="must be >= 1")

    def test_enemy_guests_invalid_entry(self):
        data = {"missions": [{"key": "m", "name": "M", "enemy_guests": [123]}]}
        result = validate_mission_templates(data)
        _assert_has_error(result, substring="expected string or mapping")

    def test_enemy_guest_dict_missing_key(self):
        data = {"missions": [{"key": "m", "name": "M", "enemy_guests": [{"label": "Boss"}]}]}
        result = validate_mission_templates(data)
        _assert_has_error(result, substring="missing required field 'key'")

    def test_enemy_troops_referential_integrity(self):
        data = {"missions": [{"key": "m", "name": "M", "enemy_troops": {"nonexistent_troop": 100}}]}
        result = validate_mission_templates(data, troop_keys={"scout", "archer"})
        _assert_has_error(result, substring="not found in troop_templates.yaml")

    def test_drop_table_referential_integrity(self):
        data = {"missions": [{"key": "m", "name": "M", "drop_table": {"nonexistent_item": 1}}]}
        result = validate_mission_templates(data, item_keys={"grain", "silver"})
        _assert_has_error(result, substring="not found in item_templates.yaml")

    def test_drop_table_silver_allowed(self):
        """Silver is a special resource key always allowed in drop tables."""
        data = {"missions": [{"key": "m", "name": "M", "drop_table": {"silver": 1000}}]}
        _assert_valid(validate_mission_templates(data, item_keys={"grain"}))

    def test_enemy_technology_types(self):
        data = {
            "missions": [
                {
                    "key": "m",
                    "name": "M",
                    "enemy_technology": {"level": "bad", "guest_level": 50},
                }
            ]
        }
        result = validate_mission_templates(data)
        _assert_has_error(result, substring="expected int")


# ===========================================================================
# forge_equipment.yaml
# ===========================================================================


class TestForgeEquipmentValidation:
    def test_valid_entry(self):
        data = {
            "equipment": {
                "equip_bumao": {
                    "category": "helmet",
                    "materials": {"tong": 5},
                    "base_duration": 120,
                    "required_forging": 1,
                }
            }
        }
        _assert_valid(validate_forge_equipment(data))

    def test_missing_equipment_key(self):
        result = validate_forge_equipment({})
        _assert_has_error(result, substring="missing required key 'equipment'")

    def test_invalid_category(self):
        data = {"equipment": {"equip_x": {"category": "plasma_cannon"}}}
        result = validate_forge_equipment(data)
        _assert_has_error(result, substring="not in allowed set")

    def test_referential_integrity(self):
        data = {"equipment": {"equip_unknown": {"category": "sword"}}}
        result = validate_forge_equipment(data, item_keys={"equip_bumao"})
        _assert_has_error(result, substring="not found in item_templates.yaml")

    def test_zero_base_duration(self):
        data = {"equipment": {"equip_x": {"base_duration": 0}}}
        result = validate_forge_equipment(data)
        _assert_has_error(result, substring="must be >= 1")


# ===========================================================================
# shop_items.yaml
# ===========================================================================


class TestShopItemsValidation:
    def test_valid_entry(self):
        data = {"items": [{"item_key": "grain", "stock": 1, "daily_refresh": False}]}
        _assert_valid(validate_shop_items(data))

    def test_missing_items_key(self):
        result = validate_shop_items({})
        _assert_has_error(result, substring="missing required key 'items'")

    def test_missing_item_key(self):
        data = {"items": [{"stock": 1}]}
        result = validate_shop_items(data)
        _assert_has_error(result, substring="missing required field 'item_key'")

    def test_referential_integrity(self):
        data = {"items": [{"item_key": "nonexistent"}]}
        result = validate_shop_items(data, item_keys={"grain"})
        _assert_has_error(result, substring="not found in item_templates.yaml")

    def test_wrong_type_daily_refresh(self):
        data = {"items": [{"item_key": "grain", "daily_refresh": "yes"}]}
        result = validate_shop_items(data)
        _assert_has_error(result, substring="expected bool")


# ===========================================================================
# arena_rules.yaml
# ===========================================================================


class TestArenaRulesValidation:
    def test_valid_minimal(self):
        data = {
            "registration": {"max_guests_per_entry": 10, "registration_silver_cost": 5000},
            "runtime": {"round_interval_seconds": 600},
            "rewards": {"base_participation_coins": 30, "rank_bonus_coins": {1: 100}},
        }
        _assert_valid(validate_arena_rules(data))

    def test_missing_sections(self):
        result = validate_arena_rules({})
        _assert_has_error(result, substring="missing required section 'registration'")
        _assert_has_error(result, substring="missing required section 'runtime'")
        _assert_has_error(result, substring="missing required section 'rewards'")

    def test_zero_registration_cost(self):
        data = {
            "registration": {"registration_silver_cost": 0},
            "runtime": {},
            "rewards": {},
        }
        result = validate_arena_rules(data)
        _assert_has_error(result, substring="must be >= 1")


# ===========================================================================
# trade_market_rules.yaml
# ===========================================================================


class TestTradeMarketRulesValidation:
    def test_valid(self):
        data = {"listing_fees": {7200: 5000, 28800: 10000}}
        _assert_valid(validate_trade_market_rules(data))

    def test_missing_listing_fees(self):
        result = validate_trade_market_rules({})
        _assert_has_error(result, substring="missing required key 'listing_fees'")

    def test_negative_fee(self):
        data = {"listing_fees": {3600: -100}}
        result = validate_trade_market_rules(data)
        _assert_has_error(result, substring="fee must be >= 0")

    def test_non_number_fee(self):
        data = {"listing_fees": {3600: "free"}}
        result = validate_trade_market_rules(data)
        _assert_has_error(result, substring="expected a number")


# ===========================================================================
# Integration: validate real configs from disk
# ===========================================================================


class TestRealConfigsPassValidation:
    """Ensure the actual data files in the repository pass validation."""

    @pytest.fixture
    def data_dir(self):
        return Path(__file__).parent.parent / "data"

    def test_item_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _assert_valid(validate_item_templates(data))

    def test_building_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "building_templates.yaml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _assert_valid(validate_building_templates(data))

    def test_guest_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "guest_templates.yaml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _assert_valid(validate_guest_templates(data))

    def test_troop_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "troop_templates.yaml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _assert_valid(validate_troop_templates(data))

    def test_mission_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "mission_templates.yaml").open("r", encoding="utf-8") as f:
            mission_data = yaml.safe_load(f)
        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as f:
            item_data = yaml.safe_load(f)
        with (data_dir / "troop_templates.yaml").open("r", encoding="utf-8") as f:
            troop_data = yaml.safe_load(f)

        item_keys = {item["key"] for item in item_data.get("items", []) if isinstance(item, dict) and "key" in item}
        troop_keys = {
            troop["key"] for troop in troop_data.get("troops", []) if isinstance(troop, dict) and "key" in troop
        }
        _assert_valid(validate_mission_templates(mission_data, item_keys=item_keys, troop_keys=troop_keys))

    def test_forge_equipment_valid(self, data_dir):
        import yaml

        with (data_dir / "forge_equipment.yaml").open("r", encoding="utf-8") as f:
            forge_data = yaml.safe_load(f)
        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as f:
            item_data = yaml.safe_load(f)

        item_keys = {item["key"] for item in item_data.get("items", []) if isinstance(item, dict) and "key" in item}
        _assert_valid(validate_forge_equipment(forge_data, item_keys=item_keys))

    def test_shop_items_valid(self, data_dir):
        import yaml

        with (data_dir / "shop_items.yaml").open("r", encoding="utf-8") as f:
            shop_data = yaml.safe_load(f)
        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as f:
            item_data = yaml.safe_load(f)

        item_keys = {item["key"] for item in item_data.get("items", []) if isinstance(item, dict) and "key" in item}
        _assert_valid(validate_shop_items(shop_data, item_keys=item_keys))

    def test_arena_rules_valid(self, data_dir):
        import yaml

        with (data_dir / "arena_rules.yaml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _assert_valid(validate_arena_rules(data))

    def test_trade_market_rules_valid(self, data_dir):
        import yaml

        with (data_dir / "trade_market_rules.yaml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _assert_valid(validate_trade_market_rules(data))

    def test_validate_all_configs(self, data_dir):
        """End-to-end: validate_all_configs on the real data dir."""
        result = validate_all_configs(data_dir)
        _assert_valid(result)


# ===========================================================================
# ValidationResult API
# ===========================================================================


class TestValidationResultAPI:
    def test_empty_result_is_valid(self):
        result = ValidationResult()
        assert result.is_valid
        assert len(result.errors) == 0

    def test_add_makes_invalid(self):
        result = ValidationResult()
        result.add("file.yaml", "path", "something wrong")
        assert not result.is_valid
        assert len(result.errors) == 1

    def test_merge(self):
        r1 = ValidationResult()
        r1.add("a.yaml", "x", "err1")
        r2 = ValidationResult()
        r2.add("b.yaml", "y", "err2")
        r1.merge(r2)
        assert len(r1.errors) == 2

    def test_error_str(self):
        result = ValidationResult()
        result.add("test.yaml", "items[0]", "bad value")
        assert "[test.yaml] items[0]: bad value" in str(result.errors[0])
