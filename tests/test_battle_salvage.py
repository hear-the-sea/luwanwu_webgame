import logging
from types import SimpleNamespace

import pytest

from core.exceptions import ItemNotFoundError
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.battle_salvage import calculate_battle_salvage, grant_battle_salvage
from gameplay.services.manor.core import ensure_manor


def test_calculate_battle_salvage_deterministic_and_uses_guest_hp_ratio():
    report = SimpleNamespace(
        seed=123,
        losses={
            "attacker": {"casualties": [{"key": "dao_jie", "lost": 10}]},
            "defender": {"casualties": []},
        },
        attacker_team=[
            {
                "guest_id": 1,
                "level": 50,
                "rarity": "blue",
                "max_hp": 100,
                "initial_hp": 50,
                "remaining_hp": 0,
            }
        ],
        defender_team=[],
    )

    exp1, equip1 = calculate_battle_salvage(report)
    exp2, equip2 = calculate_battle_salvage(report)

    # dao_jie: base_duration=180秒 → 10 * (180/3600) * 0.1 = 0.05
    # defeated guest: 50 * 2.0 * (50/100) * 0.05 = 2.5 → total int(...) = 2
    assert exp1 == 2
    assert exp2 == exp1
    assert equip2 == equip1

    expected_equipment_keys = {
        "equip_dakandao",
        "equip_yangpixue",
        "equip_shengpijia",
        "equip_tieyekui",
        "equip_zaohongma",
    }
    assert set(equip1.keys()).issubset(expected_equipment_keys)
    assert all(isinstance(v, int) and 0 <= v <= 10 for v in equip1.values())


def test_calculate_battle_salvage_counts_troop_losses_on_both_sides():
    report = SimpleNamespace(
        seed=42,
        losses={
            "attacker": {"casualties": [{"key": "dao_jie", "lost": 200}]},
            "defender": {"casualties": [{"key": "dao_jie", "lost": 200}]},
        },
        attacker_team=[],
        defender_team=[],
    )

    exp, _equip = calculate_battle_salvage(report)

    # Both sides: (200 + 200) * (180/3600) * 0.1 = 2
    assert exp == 2


def test_calculate_battle_salvage_can_limit_equipment_recovery_to_player_side():
    report = SimpleNamespace(
        seed=42,
        losses={
            "attacker": {"casualties": [{"key": "dao_jie", "lost": 200}]},
            "defender": {"casualties": [{"key": "qiang_hao", "lost": 200}]},
        },
        attacker_team=[],
        defender_team=[],
    )

    exp_all, equip_all = calculate_battle_salvage(report)
    exp_attacker_only, equip_attacker_only = calculate_battle_salvage(report, equipment_casualty_side="attacker")

    # 经验果仍按双方阵亡计算，不受装备过滤影响
    assert exp_attacker_only == exp_all == 2

    attacker_equipment_keys = {
        "equip_dakandao",
        "equip_yangpixue",
        "equip_shengpijia",
        "equip_tieyekui",
        "equip_zaohongma",
    }
    # defender 专属装备（qiang_hao）不应出现在 attacker-only 回收里
    defender_unique_key = "equip_baoweiqiang"

    assert set(equip_attacker_only.keys()).issubset(attacker_equipment_keys)
    assert defender_unique_key not in equip_attacker_only
    assert defender_unique_key in equip_all


@pytest.mark.django_db
def test_grant_battle_salvage_skips_missing_equipment_template(monkeypatch, caplog, django_user_model):
    user = django_user_model.objects.create_user(username="battle_salvage_missing_item", password="pass12345")
    manor = ensure_manor(user)
    ItemTemplate.objects.create(key="experience_fruit", name="经验果")

    from gameplay.services.inventory.core import add_item_to_inventory as original_add_item_to_inventory

    def _grant_with_missing_equipment(target_manor, item_key, quantity=1, storage_location="warehouse"):
        if item_key == "missing_equip":
            raise ItemNotFoundError(f"物品模板不存在: {item_key}")
        return original_add_item_to_inventory(target_manor, item_key, quantity, storage_location)

    monkeypatch.setattr("gameplay.services.inventory.core.add_item_to_inventory", _grant_with_missing_equipment)

    with caplog.at_level(logging.WARNING):
        grant_battle_salvage(manor, exp_fruit_count=3, equipment_recovery={"missing_equip": 2})

    exp_fruit = InventoryItem.objects.get(
        manor=manor,
        template__key="experience_fruit",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert exp_fruit.quantity == 3
    assert any("Unknown equipment template for recovery" in rec.getMessage() for rec in caplog.records)
