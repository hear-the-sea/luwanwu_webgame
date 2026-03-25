from __future__ import annotations

from types import SimpleNamespace

import pytest

from gameplay.services.missions_impl.sync_report import generate_sync_battle_report


def test_generate_sync_battle_report_offense_rejects_invalid_drop_table(monkeypatch):
    captured = {}

    def _fake_simulate_report(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=False,
        enemy_technology={},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Offense Mission",
        drop_table="bad-drop-table",
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission mapping payload"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={"archer": 1},
            defender_setup={"guest_keys": []},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_offense_rejects_invalid_drop_table_key(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when drop table key is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=False,
        enemy_technology={},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Offense Mission",
        drop_table={"": 1},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission mapping key"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={"archer": 1},
            defender_setup={"guest_keys": []},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_offense_rejects_non_string_drop_table_key(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when drop table key type is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=False,
        enemy_technology={},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Offense Mission",
        drop_table={1: 1},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission mapping key"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={"archer": 1},
            defender_setup={"guest_keys": []},
            travel_seconds=0,
            seed=1,
        )
