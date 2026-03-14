from __future__ import annotations

from types import SimpleNamespace

from gameplay.views.mission_helpers import (
    build_drop_lists,
    build_mission_data,
    build_selection_summary,
    collect_mission_asset_keys,
    parse_positive_ids,
)


def test_parse_positive_ids_deduplicates_and_preserves_order():
    assert parse_positive_ids(["3", "1", "3", "2"]) == [3, 1, 2]


def test_parse_positive_ids_rejects_non_positive_values():
    assert parse_positive_ids(["1", "0"]) is None
    assert parse_positive_ids(["1", "oops"]) is None


def test_build_mission_data_applies_extra_attempts():
    missions = [
        SimpleNamespace(key="m1", daily_limit=3),
        SimpleNamespace(key="m2", daily_limit=1),
    ]

    rows = build_mission_data(missions, {"m1": 2, "m2": 1}, {"m1": 1})

    assert rows[0]["daily_limit"] == 4
    assert rows[0]["remaining"] == 2
    assert rows[1]["daily_limit"] == 1
    assert rows[1]["remaining"] == 0


def test_build_selection_summary_handles_missing_selection():
    missions_by_key = {"m1": SimpleNamespace(key="m1", daily_limit=2)}

    selected_mission, selected_attempts, selected_daily_limit, selected_remaining = build_selection_summary(
        None,
        missions_by_key,
        {"m1": 1},
        {"m1": 1},
    )

    assert selected_mission is None
    assert selected_attempts == 0
    assert selected_daily_limit == 0
    assert selected_remaining == 0


def test_collect_mission_asset_keys_includes_choice_pool_entries():
    missions = [
        SimpleNamespace(
            enemy_guests=[],
            enemy_troops={},
            drop_table={
                "nichang_random_piece": {
                    "chance": 0.1,
                    "choices": ["equip_nichangyuyi", "equip_nichangwuxie", "equip_nichangjian"],
                }
            },
            probability_drop_table={
                "equip_nichangyuyi": 1,
                "equip_nichangwuxie": 1,
                "equip_nichangjian": 1,
            },
        )
    ]

    _enemy_keys, _troop_keys, drop_keys = collect_mission_asset_keys(missions)

    assert "nichang_random_piece" in drop_keys
    assert "equip_nichangyuyi" in drop_keys
    assert "equip_nichangwuxie" in drop_keys
    assert "equip_nichangjian" in drop_keys


def test_build_drop_lists_prefers_probability_drop_table_for_choice_pool_display():
    mission = SimpleNamespace(
        drop_table={
            "nichang_random_piece": {
                "chance": 0.1,
                "choices": ["equip_nichangyuyi", "equip_nichangwuxie", "equip_nichangjian"],
            }
        },
        probability_drop_table={
            "equip_nichangyuyi": 1,
            "equip_nichangwuxie": 1,
            "equip_nichangjian": 1,
        },
    )
    item_templates = {
        "equip_nichangyuyi": SimpleNamespace(name="霓裳羽衣"),
        "equip_nichangwuxie": SimpleNamespace(name="霓裳舞鞋"),
        "equip_nichangjian": SimpleNamespace(name="霓裳剑"),
    }
    loot_rarities = {
        "equip_nichangyuyi": "green",
        "equip_nichangwuxie": "green",
        "equip_nichangjian": "green",
    }

    guaranteed_drops, probability_drops = build_drop_lists(
        mission,
        {},
        item_templates,
        {},
        loot_rarities,
    )

    assert guaranteed_drops == []
    assert probability_drops == [
        {"label": "霓裳羽衣 x1", "rarity": "green"},
        {"label": "霓裳舞鞋 x1", "rarity": "green"},
        {"label": "霓裳剑 x1", "rarity": "green"},
    ]
