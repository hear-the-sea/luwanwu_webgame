from __future__ import annotations

from types import SimpleNamespace

from gameplay.views.mission_helpers import build_mission_data, build_selection_summary, parse_positive_ids


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
