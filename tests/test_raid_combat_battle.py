from __future__ import annotations

from types import SimpleNamespace

from gameplay.services.raid.combat import battle as combat_battle


def test_normalize_mapping_returns_dict_when_valid():
    result = combat_battle._normalize_mapping({"a": 1, "b": 2})
    assert result == {"a": 1, "b": 2}


def test_normalize_mapping_returns_empty_dict_when_invalid():
    assert combat_battle._normalize_mapping(None) == {}
    assert combat_battle._normalize_mapping("string") == {}
    assert combat_battle._normalize_mapping(123) == {}
    assert combat_battle._normalize_mapping([1, 2, 3]) == {}


def test_coerce_positive_int_returns_int_when_valid():
    assert combat_battle._coerce_positive_int(10) == 10
    assert combat_battle._coerce_positive_int("20") == 20
    assert combat_battle._coerce_positive_int(5.7) == 5


def test_coerce_positive_int_returns_zero_when_negative():
    assert combat_battle._coerce_positive_int(-5) == 0
    assert combat_battle._coerce_positive_int(0) == 0


def test_coerce_positive_int_returns_default_when_invalid():
    assert combat_battle._coerce_positive_int(None, default=10) == 10
    assert combat_battle._coerce_positive_int("invalid", default=5) == 5
    assert combat_battle._coerce_positive_int({}, default=3) == 3


def test_normalize_positive_int_mapping_filters_invalid_keys():
    raw = {"": 10, None: 20, "  ": 30, "valid": 40}
    result = combat_battle._normalize_positive_int_mapping(raw)
    assert result == {"valid": 40}


def test_normalize_positive_int_mapping_filters_non_positive_values():
    raw = {"a": 10, "b": 0, "c": -5, "d": "invalid", "e": 20}
    result = combat_battle._normalize_positive_int_mapping(raw)
    assert result == {"a": 10, "e": 20}


def test_normalize_positive_int_mapping_handles_non_dict():
    assert combat_battle._normalize_positive_int_mapping(None) == {}
    assert combat_battle._normalize_positive_int_mapping("string") == {}
    assert combat_battle._normalize_positive_int_mapping([1, 2, 3]) == {}


def test_resolve_capture_sides_attacker_wins():
    run = SimpleNamespace(attacker=SimpleNamespace(id=1), defender=SimpleNamespace(id=2))
    winner, loser = combat_battle._resolve_capture_sides(run, is_attacker_victory=True)
    assert winner.id == 1
    assert loser.id == 2


def test_resolve_capture_sides_defender_wins():
    run = SimpleNamespace(attacker=SimpleNamespace(id=1), defender=SimpleNamespace(id=2))
    winner, loser = combat_battle._resolve_capture_sides(run, is_attacker_victory=False)
    assert winner.id == 2
    assert loser.id == 1


def test_collect_losing_guest_ids_attacker_victory():
    report = SimpleNamespace(defender_team=[{"guest_id": 123}, {"guest_id": 456}], attacker_team=[])
    result = combat_battle._collect_losing_guest_ids(report, is_attacker_victory=True)
    assert set(result) == {123, 456}


def test_collect_losing_guest_ids_defender_victory():
    report = SimpleNamespace(attacker_team=[{"guest_id": 789}], defender_team=[])
    result = combat_battle._collect_losing_guest_ids(report, is_attacker_victory=False)
    assert result == [789]


def test_collect_losing_guest_ids_handles_invalid_data():
    report = SimpleNamespace(defender_team=[{"guest_id": "invalid"}, {"guest_id": 999}, {}], attacker_team=[])
    result = combat_battle._collect_losing_guest_ids(report, is_attacker_victory=True)
    assert result == [999]
