from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.exceptions import PeaceShieldUnavailableError
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.protection import activate_peace_shield


@pytest.mark.django_db
def test_activate_peace_shield_rejects_when_active_raids_exist(monkeypatch):
    user = get_user_model().objects.create_user(username="raid_protect_active", password="pass123")
    manor = ensure_manor(user)

    monkeypatch.setattr("gameplay.services.raid.protection.get_active_raid_count", lambda *_a, **_k: 1)
    monkeypatch.setattr("gameplay.services.raid.protection.get_incoming_raids", lambda *_a, **_k: [])

    with pytest.raises(PeaceShieldUnavailableError, match="出征中的队伍"):
        activate_peace_shield(manor, 3600)


@pytest.mark.django_db
def test_activate_peace_shield_rejects_when_incoming_raids_exist(monkeypatch):
    user = get_user_model().objects.create_user(username="raid_protect_incoming", password="pass123")
    manor = ensure_manor(user)

    monkeypatch.setattr("gameplay.services.raid.protection.get_active_raid_count", lambda *_a, **_k: 0)
    monkeypatch.setattr("gameplay.services.raid.protection.get_incoming_raids", lambda *_a, **_k: [object()])

    with pytest.raises(PeaceShieldUnavailableError, match="敌军来袭"):
        activate_peace_shield(manor, 3600)


@pytest.mark.django_db
def test_activate_peace_shield_extends_existing_duration(monkeypatch):
    user = get_user_model().objects.create_user(username="raid_protect_extend", password="pass123")
    manor = ensure_manor(user)

    now = timezone.now()
    manor.peace_shield_until = now + timedelta(hours=2)
    manor.save(update_fields=["peace_shield_until"])

    monkeypatch.setattr("gameplay.services.raid.protection.get_active_raid_count", lambda *_a, **_k: 0)
    monkeypatch.setattr("gameplay.services.raid.protection.get_incoming_raids", lambda *_a, **_k: [])

    activate_peace_shield(manor, 3600)

    manor.refresh_from_db(fields=["peace_shield_until"])
    expected = now + timedelta(hours=3)
    assert abs((manor.peace_shield_until - expected).total_seconds()) <= 1
