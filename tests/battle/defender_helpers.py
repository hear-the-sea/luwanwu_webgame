from __future__ import annotations

import random

from django.utils import timezone

from battle.services import _build_defender_guest_and_loadout, _extract_defender_tech_profile


def test_extract_defender_tech_profile_tolerates_invalid_technology_config():
    levels, guest_level, bonuses, skills = _extract_defender_tech_profile({"technology": "bad-config"})
    assert levels == {}
    assert guest_level == 50
    assert bonuses == {}
    assert skills is None

    levels, guest_level, bonuses, skills = _extract_defender_tech_profile(
        {"technology": {"guest_level": "bad", "guest_skills": "not-a-list"}}
    )
    assert levels == {}
    assert guest_level == 50
    assert skills is None


def test_build_defender_guest_and_loadout_tolerates_invalid_defender_setup(monkeypatch):
    monkeypatch.setattr("battle.services.generate_ai_loadout", lambda _rng: {"archer": 1})
    monkeypatch.setattr("battle.services.build_ai_guests", lambda _rng: ["ai-guest"])
    monkeypatch.setattr(
        "battle.services.build_guest_combatants",
        lambda _guests, **_kwargs: ["combatant"],
    )

    guests, loadout = _build_defender_guest_and_loadout(
        defender_guests=None,
        defender_setup="bad-config",
        defender_limit=3,
        fill_default_troops=True,
        rng=random.Random(1),
        now=timezone.now(),
        defender_guest_level=50,
        defender_guest_bonuses={},
        defender_guest_skills=None,
    )
    assert guests == ["combatant"]
    assert loadout == {"archer": 1}


def test_build_defender_guest_and_loadout_sanitizes_invalid_nested_fields(monkeypatch):
    state = {}

    monkeypatch.setattr("battle.services.generate_ai_loadout", lambda _rng: {"archer": 1})
    monkeypatch.setattr("battle.services.build_ai_guests", lambda _rng: ["ai-guest"])
    monkeypatch.setattr(
        "battle.services.build_named_ai_guests",
        lambda keys, level: state.update({"keys": keys, "level": level}) or ["named-ai"],
    )
    monkeypatch.setattr(
        "battle.services.build_guest_combatants",
        lambda _guests, **_kwargs: ["combatant"],
    )
    monkeypatch.setattr(
        "battle.services.normalize_troop_loadout",
        lambda loadout, **_kwargs: state.update({"loadout_arg": loadout}) or {"safe": 1},
    )

    guests, loadout = _build_defender_guest_and_loadout(
        defender_guests=None,
        defender_setup={"guest_keys": "bad-guests", "troop_loadout": "bad-loadout"},
        defender_limit=3,
        fill_default_troops=True,
        rng=random.Random(1),
        now=timezone.now(),
        defender_guest_level=50,
        defender_guest_bonuses={},
        defender_guest_skills=None,
    )
    assert guests == ["combatant"]
    assert loadout == {"safe": 1}
    assert state["keys"] == []
    assert state["loadout_arg"] is None
