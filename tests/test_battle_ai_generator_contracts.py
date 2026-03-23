from __future__ import annotations

import pytest

from battle.combatants_pkg.ai_generator import build_named_ai_guests


def test_build_named_ai_guests_rejects_mapping_entry_without_key():
    with pytest.raises(AssertionError, match="invalid ai guest config entry"):
        build_named_ai_guests([{"skills": ["slash"]}])


def test_build_named_ai_guests_rejects_invalid_mapping_skills():
    with pytest.raises(AssertionError, match="invalid ai guest config skills"):
        build_named_ai_guests([{"key": "enemy_guest", "skills": "bad-skills"}])


def test_build_named_ai_guests_rejects_invalid_mapping_skill_entry():
    with pytest.raises(AssertionError, match="invalid ai guest config skills entry"):
        build_named_ai_guests([{"key": "enemy_guest", "skills": [""]}])


def test_build_named_ai_guests_rejects_invalid_level():
    with pytest.raises(AssertionError, match="invalid ai guest level"):
        build_named_ai_guests([], level=0)


def test_build_named_ai_guests_rejects_unknown_template_key(monkeypatch):
    monkeypatch.setattr("battle.combatants_pkg.ai_generator.get_all_guest_templates", lambda: {})

    with pytest.raises(AssertionError, match="unknown ai guest template key"):
        build_named_ai_guests(["enemy_guest"])
