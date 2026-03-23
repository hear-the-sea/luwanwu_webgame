from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

import gameplay.services.missions_impl.attempts as mission_attempts_service
from gameplay.models import MissionTemplate
from gameplay.services.manor.core import ensure_manor
from gameplay.services.missions_impl.attempts import add_mission_extra_attempt, get_mission_daily_limit


@pytest.mark.django_db
def test_add_mission_extra_attempt_rejects_non_positive_count():
    user = get_user_model().objects.create_user(username="mission_extra_attempt_invalid", password="pass123")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="mission_attempt_invalid", name="任务次数校验")

    with pytest.raises(AssertionError, match="invalid mission extra attempt count"):
        add_mission_extra_attempt(manor, mission, 0)


def test_get_mission_daily_limit_rejects_non_positive_daily_limit(monkeypatch):
    mission = type("_Mission", (), {"daily_limit": 0})()
    monkeypatch.setattr(mission_attempts_service, "get_mission_extra_attempts", lambda *_a, **_k: 0)

    with pytest.raises(AssertionError, match="invalid mission daily_limit"):
        get_mission_daily_limit(object(), mission)


def test_get_mission_daily_limit_rejects_invalid_extra_attempts(monkeypatch):
    mission = type("_Mission", (), {"daily_limit": 3})()
    monkeypatch.setattr(mission_attempts_service, "get_mission_extra_attempts", lambda *_a, **_k: True)

    with pytest.raises(AssertionError, match="invalid mission extra attempts"):
        get_mission_daily_limit(object(), mission)
