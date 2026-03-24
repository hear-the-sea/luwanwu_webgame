from __future__ import annotations

from core.utils.yaml_schema import validate_ranch_production, validate_smithy_production, validate_stable_production
from tests.yaml_schema_new_configs.support import assert_invalid


def test_smithy_production_rejects_non_dict_root():
    result = validate_smithy_production("bad")
    assert_invalid(result)


def test_smithy_production_rejects_missing_production():
    result = validate_smithy_production({})
    assert_invalid(result, substring="missing required key 'production'")


def test_smithy_production_rejects_unknown_category():
    data = {"production": {"tong": {"cost_type": "silver", "cost_amount": 1, "base_duration": 60, "category": "magic"}}}
    result = validate_smithy_production(data)
    assert_invalid(result, substring="category")


def test_smithy_production_rejects_zero_base_duration():
    data = {"production": {"tong": {"cost_type": "silver", "cost_amount": 1, "base_duration": 0}}}
    result = validate_smithy_production(data)
    assert_invalid(result, substring="base_duration")


def test_ranch_production_rejects_non_dict_root():
    result = validate_ranch_production(42)
    assert_invalid(result)


def test_ranch_production_rejects_missing_production():
    result = validate_ranch_production({})
    assert_invalid(result, substring="missing required key 'production'")


def test_ranch_production_rejects_zero_grain_cost():
    data = {"production": {"ji": {"grain_cost": 0, "base_duration": 120}}}
    result = validate_ranch_production(data)
    assert_invalid(result, substring="grain_cost")


def test_stable_production_rejects_non_dict_root():
    result = validate_stable_production([])
    assert_invalid(result)


def test_stable_production_rejects_missing_production():
    result = validate_stable_production({})
    assert_invalid(result, substring="missing required key 'production'")


def test_stable_production_rejects_negative_grain_cost():
    data = {"production": {"equip_horse": {"grain_cost": -100, "base_duration": 120}}}
    result = validate_stable_production(data)
    assert_invalid(result, substring="grain_cost")


def test_stable_production_flags_unknown_item_key():
    known_items = {"equip_sword"}
    data = {"production": {"equip_unknown_horse": {"grain_cost": 500, "base_duration": 120}}}
    result = validate_stable_production(data, item_keys=known_items)
    assert_invalid(result, substring="not found in item_templates.yaml")
