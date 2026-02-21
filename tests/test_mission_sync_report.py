from __future__ import annotations

from types import SimpleNamespace

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

    monkeypatch.setattr("battle.combatants.build_named_ai_guests", _build_named_ai_guests)
    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology="bad-config",
        enemy_guests="bad-guests",
        enemy_troops="bad-troops",
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
    assert captured["attacker_guests"][0].level == 50
    assert state["keys"] == []


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
