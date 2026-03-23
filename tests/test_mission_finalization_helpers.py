from __future__ import annotations

from types import SimpleNamespace

import pytest

from gameplay.services.missions_impl.finalization_helpers import (
    build_mission_drops_with_salvage,
    extract_report_guest_state,
    return_attacker_troops_after_mission,
)


def test_extract_report_guest_state_rejects_invalid_hp_update_payload():
    report = SimpleNamespace(
        losses={"attacker": {"hp_updates": {"guest-1": "bad"}}},
        attacker_team=[],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report hp update payload"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_invalid_team_entry():
    report = SimpleNamespace(
        losses={},
        attacker_team=[{"guest_id": "x", "remaining_hp": 10}],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report team entry"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_negative_hp_update():
    report = SimpleNamespace(
        losses={"attacker": {"hp_updates": {1: -1}}},
        attacker_team=[],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report hp update payload"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_non_positive_hp_update_guest_id():
    report = SimpleNamespace(
        losses={"attacker": {"hp_updates": {0: 10}}},
        attacker_team=[],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report hp update payload"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_invalid_losses_container():
    report = SimpleNamespace(
        losses="bad-losses",
        attacker_team=[],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report.losses"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_invalid_team_entries_container():
    report = SimpleNamespace(
        losses={},
        attacker_team="bad-team",
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report.team_entries"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_non_mapping_team_entry():
    report = SimpleNamespace(
        losses={},
        attacker_team=["bad-entry"],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report team entry"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_negative_team_entry_hp():
    report = SimpleNamespace(
        losses={},
        attacker_team=[{"guest_id": 1, "remaining_hp": -1}],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report team entry"):
        extract_report_guest_state(report, "attacker")


def test_extract_report_guest_state_rejects_non_positive_team_entry_guest_id():
    report = SimpleNamespace(
        losses={},
        attacker_team=[{"guest_id": 0, "remaining_hp": 10}],
        defender_team=[],
    )

    with pytest.raises(AssertionError, match="invalid mission report team entry"):
        extract_report_guest_state(report, "attacker")


def test_return_attacker_troops_after_mission_rejects_invalid_troop_loadout():
    locked_run = SimpleNamespace(
        mission=SimpleNamespace(is_defense=False),
        troop_loadout="bad-loadout",
        is_retreating=False,
        manor=SimpleNamespace(id=1),
        id=11,
    )

    with pytest.raises(AssertionError, match="invalid mission troop_loadout"):
        return_attacker_troops_after_mission(
            locked_run, report=None, logger=SimpleNamespace(warning=lambda *_a, **_k: None)
        )


def test_build_mission_drops_with_salvage_rejects_invalid_report_drops():
    locked_run = SimpleNamespace(mission=SimpleNamespace(is_defense=False, drop_table={}), id=12)
    report = SimpleNamespace(drops="bad-drops")

    with pytest.raises(AssertionError, match="invalid mission report.drops"):
        build_mission_drops_with_salvage(
            locked_run,
            report,
            "attacker",
            logger=SimpleNamespace(),
            resolve_defense_drops_if_missing=lambda *_a, **_k: {},
        )
