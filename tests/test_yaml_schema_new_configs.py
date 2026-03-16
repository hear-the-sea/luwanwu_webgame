"""Negative tests for the 13 new YAML config validators added in P2-4."""

from __future__ import annotations

from core.utils.yaml_schema import (
    validate_arena_rewards,
    validate_auction_items,
    validate_forge_blueprints,
    validate_forge_decompose,
    validate_guest_growth_rules,
    validate_guest_skills,
    validate_guild_rules,
    validate_ranch_production,
    validate_recruitment_rarity_weights,
    validate_smithy_production,
    validate_stable_production,
    validate_technology_templates,
    validate_warehouse_production,
)

# ---------------------------------------------------------------------------
# warehouse_production.yaml
# ---------------------------------------------------------------------------


def test_warehouse_production_rejects_non_dict_root():
    result = validate_warehouse_production("not a dict")
    assert not result.is_valid
    assert any("expected a mapping" in e.message for e in result.errors)


def test_warehouse_production_rejects_missing_levels():
    result = validate_warehouse_production({"equipment": {}})
    assert not result.is_valid
    assert any("missing required key 'levels'" in e.message for e in result.errors)


def test_warehouse_production_rejects_negative_contribution_cost():
    data = {"equipment": {"levels": {1: [{"item_key": "gear_green_random", "quantity": 2, "contribution_cost": -10}]}}}
    result = validate_warehouse_production(data)
    assert not result.is_valid
    assert any("contribution_cost" in e.message for e in result.errors)


def test_warehouse_production_rejects_unknown_tech_key():
    data = {"unknown_tech": {"levels": {1: [{"item_key": "x", "quantity": 1, "contribution_cost": 10}]}}}
    result = validate_warehouse_production(data)
    assert not result.is_valid
    assert any("unknown tech section" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# auction_items.yaml
# ---------------------------------------------------------------------------


def test_auction_items_rejects_non_dict_root():
    result = validate_auction_items([])
    assert not result.is_valid
    assert any("expected a mapping" in e.message for e in result.errors)


def test_auction_items_rejects_missing_items():
    result = validate_auction_items({"settings": {"cycle_days": 3}})
    assert not result.is_valid
    assert any("missing required key 'items'" in e.message for e in result.errors)


def test_auction_items_rejects_zero_starting_price():
    data = {"items": [{"item_key": "some_item", "slots": 1, "quantity_per_slot": 1, "starting_price": 0}]}
    result = validate_auction_items(data)
    assert not result.is_valid
    assert any("starting_price" in e.message for e in result.errors)


def test_auction_items_rejects_duplicate_item_keys():
    data = {
        "items": [
            {"item_key": "item_a", "slots": 1, "quantity_per_slot": 1, "starting_price": 5},
            {"item_key": "item_a", "slots": 1, "quantity_per_slot": 1, "starting_price": 5},
        ]
    }
    result = validate_auction_items(data)
    assert not result.is_valid
    assert any("duplicate" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# forge_blueprints.yaml
# ---------------------------------------------------------------------------


def test_forge_blueprints_rejects_non_dict_root():
    result = validate_forge_blueprints("bad")
    assert not result.is_valid


def test_forge_blueprints_rejects_missing_recipes():
    result = validate_forge_blueprints({})
    assert not result.is_valid
    assert any("missing required key 'recipes'" in e.message for e in result.errors)


def test_forge_blueprints_rejects_zero_quantity_out():
    data = {
        "recipes": [
            {
                "blueprint_key": "bp_x",
                "result_item_key": "equip_x",
                "required_forging": 5,
                "quantity_out": 0,
            }
        ]
    }
    result = validate_forge_blueprints(data)
    assert not result.is_valid
    assert any("quantity_out" in e.message for e in result.errors)


def test_forge_blueprints_rejects_non_dict_costs():
    data = {
        "recipes": [
            {
                "blueprint_key": "bp_x",
                "result_item_key": "equip_x",
                "required_forging": 5,
                "quantity_out": 1,
                "costs": "not a dict",
            }
        ]
    }
    result = validate_forge_blueprints(data)
    assert not result.is_valid
    assert any("'costs' expected a mapping" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# forge_decompose.yaml
# ---------------------------------------------------------------------------


def test_forge_decompose_rejects_non_dict_root():
    result = validate_forge_decompose(42)
    assert not result.is_valid


def test_forge_decompose_rejects_missing_supported_rarities():
    result = validate_forge_decompose({"base_materials": {}})
    assert not result.is_valid
    assert any("missing required key 'supported_rarities'" in e.message for e in result.errors)


def test_forge_decompose_rejects_unknown_rarity_in_supported():
    result = validate_forge_decompose({"supported_rarities": ["green", "legendary"]})
    assert not result.is_valid
    assert any("unknown rarity 'legendary'" in e.message for e in result.errors)


def test_forge_decompose_rejects_probability_out_of_range():
    data = {
        "supported_rarities": ["green"],
        "chance_rewards": {"green": {"wood_essence": 1.5}},
    }
    result = validate_forge_decompose(data)
    assert not result.is_valid
    assert any("probability must be between 0 and 1" in e.message for e in result.errors)


def test_forge_decompose_rejects_invalid_material_range():
    data = {
        "supported_rarities": ["green"],
        "base_materials": {"green": {"tong": [2]}},  # must be [min, max]
    }
    result = validate_forge_decompose(data)
    assert not result.is_valid
    assert any("list of [min, max]" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# guest_skills.yaml
# ---------------------------------------------------------------------------


def test_guest_skills_rejects_non_dict_root():
    result = validate_guest_skills([])
    assert not result.is_valid


def test_guest_skills_rejects_missing_skills():
    result = validate_guest_skills({})
    assert not result.is_valid
    assert any("missing required key 'skills'" in e.message for e in result.errors)


def test_guest_skills_rejects_unknown_rarity():
    data = {"skills": [{"key": "fire_ball", "name": "Fire Ball", "rarity": "legendary"}]}
    result = validate_guest_skills(data)
    assert not result.is_valid
    assert any("rarity" in e.message for e in result.errors)


def test_guest_skills_rejects_invalid_kind():
    data = {"skills": [{"key": "fire_ball", "name": "Fire Ball", "rarity": "green", "kind": "support"}]}
    result = validate_guest_skills(data)
    assert not result.is_valid
    assert any("kind" in e.message for e in result.errors)


def test_guest_skills_rejects_probability_out_of_range():
    data = {"skills": [{"key": "fire_ball", "name": "Fire Ball", "rarity": "green", "base_probability": 1.5}]}
    result = validate_guest_skills(data)
    assert not result.is_valid
    assert any("base_probability" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# recruitment_rarity_weights.yaml
# ---------------------------------------------------------------------------


def test_recruitment_rarity_weights_rejects_non_dict_root():
    result = validate_recruitment_rarity_weights("nope")
    assert not result.is_valid


def test_recruitment_rarity_weights_rejects_missing_total_weight():
    result = validate_recruitment_rarity_weights({"weights": {"green": 100}})
    assert not result.is_valid
    assert any("missing required key 'total_weight'" in e.message for e in result.errors)


def test_recruitment_rarity_weights_rejects_missing_weights():
    result = validate_recruitment_rarity_weights({"total_weight": 1000})
    assert not result.is_valid
    assert any("missing required key 'weights'" in e.message for e in result.errors)


def test_recruitment_rarity_weights_rejects_negative_weight():
    data = {"total_weight": 1000, "weights": {"green": -5}}
    result = validate_recruitment_rarity_weights(data)
    assert not result.is_valid
    assert any("weight must be >= 0" in e.message for e in result.errors)


def test_recruitment_rarity_weights_rejects_unknown_rarity():
    data = {"total_weight": 1000, "weights": {"legendary": 100}}
    result = validate_recruitment_rarity_weights(data)
    assert not result.is_valid
    assert any("unknown rarity" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# arena_rewards.yaml
# ---------------------------------------------------------------------------


def test_arena_rewards_rejects_non_dict_root():
    result = validate_arena_rewards([])
    assert not result.is_valid


def test_arena_rewards_rejects_missing_rewards():
    result = validate_arena_rewards({})
    assert not result.is_valid
    assert any("missing required key 'rewards'" in e.message for e in result.errors)


def test_arena_rewards_rejects_zero_cost_coins():
    data = {"rewards": [{"key": "grain_pack", "name": "Grain Pack", "cost_coins": 0}]}
    result = validate_arena_rewards(data)
    assert not result.is_valid
    assert any("cost_coins" in e.message for e in result.errors)


def test_arena_rewards_rejects_duplicate_keys():
    data = {
        "rewards": [
            {"key": "grain_pack", "name": "Grain Pack", "cost_coins": 80},
            {"key": "grain_pack", "name": "Grain Pack 2", "cost_coins": 100},
        ]
    }
    result = validate_arena_rewards(data)
    assert not result.is_valid
    assert any("duplicate" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# smithy_production.yaml
# ---------------------------------------------------------------------------


def test_smithy_production_rejects_non_dict_root():
    result = validate_smithy_production("bad")
    assert not result.is_valid


def test_smithy_production_rejects_missing_production():
    result = validate_smithy_production({})
    assert not result.is_valid
    assert any("missing required key 'production'" in e.message for e in result.errors)


def test_smithy_production_rejects_unknown_category():
    data = {"production": {"tong": {"cost_type": "silver", "cost_amount": 1, "base_duration": 60, "category": "magic"}}}
    result = validate_smithy_production(data)
    assert not result.is_valid
    assert any("category" in e.message for e in result.errors)


def test_smithy_production_rejects_zero_base_duration():
    data = {"production": {"tong": {"cost_type": "silver", "cost_amount": 1, "base_duration": 0}}}
    result = validate_smithy_production(data)
    assert not result.is_valid
    assert any("base_duration" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# ranch_production.yaml
# ---------------------------------------------------------------------------


def test_ranch_production_rejects_non_dict_root():
    result = validate_ranch_production(42)
    assert not result.is_valid


def test_ranch_production_rejects_missing_production():
    result = validate_ranch_production({})
    assert not result.is_valid
    assert any("missing required key 'production'" in e.message for e in result.errors)


def test_ranch_production_rejects_zero_grain_cost():
    data = {"production": {"ji": {"grain_cost": 0, "base_duration": 120}}}
    result = validate_ranch_production(data)
    assert not result.is_valid
    assert any("grain_cost" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# stable_production.yaml
# ---------------------------------------------------------------------------


def test_stable_production_rejects_non_dict_root():
    result = validate_stable_production([])
    assert not result.is_valid


def test_stable_production_rejects_missing_production():
    result = validate_stable_production({})
    assert not result.is_valid
    assert any("missing required key 'production'" in e.message for e in result.errors)


def test_stable_production_rejects_negative_grain_cost():
    data = {"production": {"equip_horse": {"grain_cost": -100, "base_duration": 120}}}
    result = validate_stable_production(data)
    assert not result.is_valid
    assert any("grain_cost" in e.message for e in result.errors)


def test_stable_production_flags_unknown_item_key():
    known_items = {"equip_sword"}
    data = {"production": {"equip_unknown_horse": {"grain_cost": 500, "base_duration": 120}}}
    result = validate_stable_production(data, item_keys=known_items)
    assert not result.is_valid
    assert any("not found in item_templates.yaml" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# guild_rules.yaml
# ---------------------------------------------------------------------------


def test_guild_rules_rejects_non_dict_root():
    result = validate_guild_rules("oops")
    assert not result.is_valid


def test_guild_rules_rejects_missing_required_sections():
    result = validate_guild_rules({})
    assert not result.is_valid
    # Should report missing pagination, creation, contribution
    assert len([e for e in result.errors if "missing required section" in e.message]) >= 3


def test_guild_rules_rejects_zero_page_size():
    data = {
        "pagination": {"guild_list_page_size": 0, "guild_hall_display_limit": 20},
        "creation": {},
        "contribution": {},
    }
    result = validate_guild_rules(data)
    assert not result.is_valid
    assert any("guild_list_page_size" in e.message for e in result.errors)


def test_guild_rules_rejects_negative_daily_limit():
    data = {
        "pagination": {"guild_list_page_size": 20, "guild_hall_display_limit": 20},
        "creation": {},
        "contribution": {"daily_limits": {"silver": -1}},
    }
    result = validate_guild_rules(data)
    assert not result.is_valid
    assert any("non-negative" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# guest_growth_rules.yaml
# ---------------------------------------------------------------------------


def test_guest_growth_rules_rejects_non_dict_root():
    result = validate_guest_growth_rules([])
    assert not result.is_valid


def test_guest_growth_rules_rejects_unknown_rarity_in_hp_profiles():
    data = {"rarity_hp_profiles": {"legendary": {"base": 999}}}
    result = validate_guest_growth_rules(data)
    assert not result.is_valid
    assert any("unknown rarity 'legendary'" in e.message for e in result.errors)


def test_guest_growth_rules_rejects_non_positive_hp_base():
    data = {"rarity_hp_profiles": {"green": {"base": 0}}}
    result = validate_guest_growth_rules(data)
    assert not result.is_valid
    assert any("base" in e.message for e in result.errors)


def test_guest_growth_rules_rejects_malformed_growth_range():
    data = {"rarity_attribute_growth_range": {"green": [3]}}  # needs [min, max]
    result = validate_guest_growth_rules(data)
    assert not result.is_valid
    assert any("list of [min, max]" in e.message for e in result.errors)


def test_guest_growth_rules_rejects_unknown_archetype():
    data = {"archetype_attribute_weights": {"soldier": {"force": 40}}}
    result = validate_guest_growth_rules(data)
    assert not result.is_valid
    assert any("unknown archetype 'soldier'" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# technology_templates.yaml
# ---------------------------------------------------------------------------


def test_technology_templates_rejects_non_dict_root():
    result = validate_technology_templates("nope")
    assert not result.is_valid


def test_technology_templates_rejects_missing_technologies():
    result = validate_technology_templates({"categories": []})
    assert not result.is_valid
    assert any("missing required key 'technologies'" in e.message for e in result.errors)


def test_technology_templates_rejects_unknown_category():
    data = {
        "technologies": [
            {
                "key": "fire_art",
                "name": "Fire Art",
                "category": "magic",
                "effect_type": "bonus",
                "max_level": 10,
                "base_cost": 1000,
            }
        ]
    }
    result = validate_technology_templates(data)
    assert not result.is_valid
    assert any("category" in e.message for e in result.errors)


def test_technology_templates_rejects_zero_max_level():
    data = {
        "technologies": [
            {
                "key": "scout_art",
                "name": "Scout Art",
                "category": "basic",
                "effect_type": "scout_bonus",
                "max_level": 0,
                "base_cost": 8000,
            }
        ]
    }
    result = validate_technology_templates(data)
    assert not result.is_valid
    assert any("max_level" in e.message for e in result.errors)


def test_technology_templates_rejects_duplicate_tech_keys():
    data = {
        "technologies": [
            {
                "key": "scout_art",
                "name": "Scout Art",
                "category": "basic",
                "effect_type": "scout_bonus",
                "max_level": 10,
                "base_cost": 8000,
            },
            {
                "key": "scout_art",
                "name": "Scout Art Copy",
                "category": "martial",
                "effect_type": "scout_bonus",
                "max_level": 5,
                "base_cost": 5000,
            },
        ]
    }
    result = validate_technology_templates(data)
    assert not result.is_valid
    assert any("duplicate" in e.message for e in result.errors)


def test_technology_templates_rejects_negative_base_cost():
    data = {
        "technologies": [
            {
                "key": "scout_art",
                "name": "Scout Art",
                "category": "basic",
                "effect_type": "scout_bonus",
                "max_level": 10,
                "base_cost": -1,
            }
        ]
    }
    result = validate_technology_templates(data)
    assert not result.is_valid
    assert any("base_cost" in e.message for e in result.errors)
