from types import SimpleNamespace

from gameplay.services.battle_salvage import calculate_battle_salvage


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

    # dao_jie: base_duration=180 → 10 * (180/60) * 0.1 = 3
    # defeated guest: 50 * 2.0 * (50/100) * 0.05 = 2.5 → total int(...) = 5
    assert exp1 == 5
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
            "attacker": {"casualties": [{"key": "dao_jie", "lost": 10}]},
            "defender": {"casualties": [{"key": "dao_jie", "lost": 10}]},
        },
        attacker_team=[],
        defender_team=[],
    )

    exp, _equip = calculate_battle_salvage(report)

    # Both sides: (10 + 10) * (180/60) * 0.1 = 6
    assert exp == 6

