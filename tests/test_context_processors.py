from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from gameplay.context_processors import notifications
from gameplay.services.manor import ensure_manor


pytestmark = pytest.mark.django_db


def test_notifications_anonymous_tolerates_cache_and_redis_failures(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    monkeypatch.setattr(
        "gameplay.context_processors.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache read failed")),
    )
    monkeypatch.setattr(
        "gameplay.context_processors.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache write failed")),
    )
    monkeypatch.setattr(
        "gameplay.context_processors.get_redis_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("redis down")),
    )

    context = notifications(request)
    assert context["message_unread_count"] == 0
    assert context["online_user_count"] >= 0
    assert context["total_user_count"] >= 0


def test_notifications_anonymous_handles_corrupted_cached_online_value(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    def fake_cache_get(key, default=None):
        if key == "stats:total_users_count":
            return 7
        if key == "stats:online_users_count":
            return "invalid-int"
        return default

    monkeypatch.setattr("gameplay.context_processors.cache.get", fake_cache_get)

    context = notifications(request)
    assert context["total_user_count"] == 7
    assert context["online_user_count"] == 0


def test_notifications_authenticated_falls_back_when_sidebar_cache_payload_invalid(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_user", password="pass")
    manor = ensure_manor(user)
    request = RequestFactory().get("/")
    request.user = user

    def fake_cache_get(key, default=None):
        if key == "stats:total_users_count":
            return 5
        if key == "stats:online_users_count":
            return 2
        if key == f"sidebar:rank:{manor.id}":
            return None
        if key == f"sidebar:raids:{manor.id}":
            return "corrupted"
        return default

    monkeypatch.setattr("gameplay.context_processors.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.context_processors.cache.set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("gameplay.context_processors.unread_message_count", lambda _manor: 4)
    monkeypatch.setattr("gameplay.services.ranking.get_player_rank", lambda _manor: 9)
    monkeypatch.setattr("gameplay.services.raid.get_active_raids", lambda _manor: ["r1"])
    monkeypatch.setattr("gameplay.services.raid.get_active_scouts", lambda _manor: ["s1", "s2"])
    monkeypatch.setattr("gameplay.services.raid.get_incoming_raids", lambda _manor: [])

    context = notifications(request)
    assert context["message_unread_count"] == 4
    assert context["sidebar_rank"] == 9
    assert context["sidebar_active_raids"] == ["r1"]
    assert context["sidebar_active_scouts"] == ["s1", "s2"]
    assert context["sidebar_incoming_raids"] == []
