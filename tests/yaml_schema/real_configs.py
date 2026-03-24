from __future__ import annotations

from pathlib import Path

import pytest

from core.utils.yaml_schema import (
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
from tests.yaml_schema.support import assert_valid


class TestRealConfigsPassValidation:
    @pytest.fixture
    def data_dir(self):
        return Path(__file__).resolve().parents[2] / "data"

    def test_item_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        assert_valid(validate_item_templates(data))

    def test_building_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "building_templates.yaml").open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        assert_valid(validate_building_templates(data))

    def test_guest_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "guest_templates.yaml").open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        assert_valid(validate_guest_templates(data))

    def test_troop_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "troop_templates.yaml").open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        assert_valid(validate_troop_templates(data))

    def test_mission_templates_valid(self, data_dir):
        import yaml

        with (data_dir / "mission_templates.yaml").open("r", encoding="utf-8") as handle:
            mission_data = yaml.safe_load(handle)
        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as handle:
            item_data = yaml.safe_load(handle)
        with (data_dir / "troop_templates.yaml").open("r", encoding="utf-8") as handle:
            troop_data = yaml.safe_load(handle)

        item_keys = {item["key"] for item in item_data.get("items", []) if isinstance(item, dict) and "key" in item}
        troop_keys = {
            troop["key"] for troop in troop_data.get("troops", []) if isinstance(troop, dict) and "key" in troop
        }
        assert_valid(validate_mission_templates(mission_data, item_keys=item_keys, troop_keys=troop_keys))

    def test_forge_equipment_valid(self, data_dir):
        import yaml

        with (data_dir / "forge_equipment.yaml").open("r", encoding="utf-8") as handle:
            forge_data = yaml.safe_load(handle)
        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as handle:
            item_data = yaml.safe_load(handle)

        item_keys = {item["key"] for item in item_data.get("items", []) if isinstance(item, dict) and "key" in item}
        assert_valid(validate_forge_equipment(forge_data, item_keys=item_keys))

    def test_shop_items_valid(self, data_dir):
        import yaml

        with (data_dir / "shop_items.yaml").open("r", encoding="utf-8") as handle:
            shop_data = yaml.safe_load(handle)
        with (data_dir / "item_templates.yaml").open("r", encoding="utf-8") as handle:
            item_data = yaml.safe_load(handle)

        item_keys = {item["key"] for item in item_data.get("items", []) if isinstance(item, dict) and "key" in item}
        assert_valid(validate_shop_items(shop_data, item_keys=item_keys))

    def test_arena_rules_valid(self, data_dir):
        import yaml

        with (data_dir / "arena_rules.yaml").open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        assert_valid(validate_arena_rules(data))

    def test_trade_market_rules_valid(self, data_dir):
        import yaml

        with (data_dir / "trade_market_rules.yaml").open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        assert_valid(validate_trade_market_rules(data))

    def test_validate_all_configs(self, data_dir):
        result = validate_all_configs(data_dir)
        assert_valid(result)
