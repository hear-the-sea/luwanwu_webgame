from __future__ import annotations

from types import SimpleNamespace

import pytest

from gameplay.services.missions_impl.sync_report import generate_sync_battle_report


def test_generate_sync_battle_report_defense_tolerates_invalid_enemy_technology(monkeypatch):
    captured = {}
    state = {}

    def _build_named_ai_guests(keys, level):
        state["keys"] = keys
        return [SimpleNamespace(level=level)]

    def _fake_simulate_report(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", _build_named_ai_guests)
    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology="bad-config",
        enemy_guests="bad-guests",
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    report = generate_sync_battle_report(
        manor=manor,
        mission=mission,
        guests=[],
        loadout={},
        defender_setup={},
        travel_seconds=0,
        seed=1,
    )

    assert report == {"ok": True}
    assert captured["attacker_tech_levels"] == {}
    assert captured["attacker_guest_bonuses"] is None
    assert captured["attacker_guest_skills"] is None
    assert captured["troop_loadout"] == {}
    assert captured["validate_attacker_troop_capacity"] is False
    assert captured["attacker_guests"][0].level == 50
    assert state["keys"] == []


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_troops(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when mission troop loadout is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={},
        enemy_guests=[],
        enemy_troops={"archer": "bad"},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission troop loadout quantity"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_guest_level(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest level config is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={"guest_level": 0},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy guest level"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_offense_sanitizes_invalid_drop_table(monkeypatch):
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

    report = generate_sync_battle_report(
        manor=manor,
        mission=mission,
        guests=[],
        loadout={"archer": 1},
        defender_setup={"guest_keys": []},
        travel_seconds=0,
        seed=1,
    )

    assert report == {"ok": True}
    assert captured["drop_table"] == {}
