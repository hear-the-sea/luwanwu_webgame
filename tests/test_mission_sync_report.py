from __future__ import annotations

from types import SimpleNamespace

import pytest

from gameplay.services.missions_impl.sync_report import generate_sync_battle_report


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_technology(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy technology config is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology="bad-config",
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy technology"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_guests(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest config is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={},
        enemy_guests="bad-guests",
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission guest configs"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_guest_mapping_entry(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest mapping entry is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={},
        enemy_guests=[{"skills": ["slash"]}],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission guest config entry"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_guest_mapping_skills(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest mapping skills are broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={},
        enemy_guests=[{"key": "enemy_guest", "skills": "bad-skills"}],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission guest config skills"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


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


def test_generate_sync_battle_report_defense_rejects_bool_enemy_troops_quantity(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when mission troop loadout quantity is boolean")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={},
        enemy_guests=[],
        enemy_troops={"archer": True},
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


def test_generate_sync_battle_report_defense_rejects_bool_enemy_guest_level(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest level is boolean")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={"guest_level": True},
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


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_guest_skills(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest skills config is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={"guest_skills": "bad-skills"},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy guest skills"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_technology_key(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy technology key is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={"": 1},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy technology key"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_non_string_enemy_technology_key(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy technology key type is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={1: 1},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy technology key"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_invalid_enemy_guest_skill_entry(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest skills entry is broken")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={"guest_skills": [123]},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy guest skills entry"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


def test_generate_sync_battle_report_defense_rejects_blank_enemy_guest_skill_entry(monkeypatch):
    def _fake_simulate_report(**_kwargs):
        raise AssertionError("should not simulate when enemy guest skills entry is blank")

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)
    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", lambda *_a, **_k: [])

    mission = SimpleNamespace(
        is_defense=True,
        enemy_technology={"guest_skills": ["   "]},
        enemy_guests=[],
        enemy_troops={},
        battle_type="task",
        name="Defense Mission",
        drop_table={},
    )
    manor = SimpleNamespace(max_squad_size=6)

    with pytest.raises(AssertionError, match="invalid mission enemy guest skills entry"):
        generate_sync_battle_report(
            manor=manor,
            mission=mission,
            guests=[],
            loadout={},
            defender_setup={},
            travel_seconds=0,
            seed=1,
        )


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
