from __future__ import annotations

from importlib import import_module

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session

from accounts.models import UserActiveSession
from websocket.consumers.session_guard import WebSocketSessionValidationUnavailable, is_websocket_session_valid


def _build_session_for_user(user):
    session_store = import_module(settings.SESSION_ENGINE).SessionStore()
    session_store["_auth_user_id"] = str(user.id)
    session_store["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
    session_store["_auth_user_hash"] = user.get_session_auth_hash()
    session_store.save()
    return session_store


@pytest.mark.django_db
def test_is_websocket_session_valid_accepts_matching_active_session(django_user_model):
    user = django_user_model.objects.create_user(username="ws_guard_ok", password="pass123")
    session = _build_session_for_user(user)
    UserActiveSession.objects.create(user=user, session_key=session.session_key)

    assert is_websocket_session_valid({"user": user, "session": session}) is True


@pytest.mark.django_db
def test_is_websocket_session_valid_rejects_stale_session_after_relogin(django_user_model):
    user = django_user_model.objects.create_user(username="ws_guard_stale", password="pass123")
    stale_session = _build_session_for_user(user)
    fresh_session = _build_session_for_user(user)
    UserActiveSession.objects.create(user=user, session_key=fresh_session.session_key)

    assert is_websocket_session_valid({"user": user, "session": stale_session}) is False


@pytest.mark.django_db
def test_is_websocket_session_valid_rejects_deleted_session(django_user_model):
    user = django_user_model.objects.create_user(username="ws_guard_deleted", password="pass123")
    session = _build_session_for_user(user)
    UserActiveSession.objects.create(user=user, session_key=session.session_key)
    Session.objects.filter(session_key=session.session_key).delete()

    assert is_websocket_session_valid({"user": user, "session": session}) is False


@pytest.mark.django_db
def test_is_websocket_session_valid_raises_when_session_store_unavailable(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="ws_guard_unavailable", password="pass123")
    session = _build_session_for_user(user)
    UserActiveSession.objects.create(user=user, session_key=session.session_key)

    def _boom(_session_key):
        raise RuntimeError("session backend down")

    monkeypatch.setattr(session, "exists", _boom)

    with pytest.raises(WebSocketSessionValidationUnavailable, match="unavailable"):
        is_websocket_session_valid({"user": user, "session": session})
