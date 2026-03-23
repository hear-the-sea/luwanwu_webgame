from __future__ import annotations

from types import SimpleNamespace

import pytest

from gameplay.services.missions_impl.finalization_helpers import extract_report_guest_state


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
