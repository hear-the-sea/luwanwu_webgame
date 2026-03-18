import pytest
from django.core.cache import cache
from django.db import DatabaseError

from accounts.models import UserActiveSession
from accounts.utils import USER_SESSION_CACHE_PREFIX, USER_SESSION_CACHE_TTL


@pytest.mark.django_db
def test_single_session_middleware_logs_out_stale_session(client, django_user_model):
    user = django_user_model.objects.create_user(username="single_session_mw", password="pass123")
    client.force_login(user)

    UserActiveSession.objects.filter(user=user).update(session_key="canonical-session-key")
    cache.set(
        f"{USER_SESSION_CACHE_PREFIX}{user.id}",
        "canonical-session-key",
        timeout=USER_SESSION_CACHE_TTL,
    )

    response = client.get("/health/live")

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_single_session_middleware_keeps_matching_session(client, django_user_model):
    user = django_user_model.objects.create_user(username="single_session_ok", password="pass123")
    client.force_login(user)
    current_session_key = client.session.session_key

    UserActiveSession.objects.filter(user=user).update(session_key=current_session_key)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert client.session.get("_auth_user_id") == str(user.id)


@pytest.mark.django_db
def test_single_session_middleware_backfills_missing_authoritative_record(client, django_user_model):
    user = django_user_model.objects.create_user(username="single_session_backfill", password="pass123")
    client.force_login(user)
    current_session_key = client.session.session_key

    response = client.get("/health/live")

    assert response.status_code == 200
    assert UserActiveSession.objects.get(user=user).session_key == current_session_key
    assert client.session.get("_auth_user_id") == str(user.id)


@pytest.mark.django_db
def test_single_session_middleware_backfills_authoritative_record_from_legacy_cache(client, django_user_model):
    user = django_user_model.objects.create_user(username="single_session_legacy_cache", password="pass123")
    client.force_login(user)
    current_session_key = client.session.session_key
    cache.set(
        f"{USER_SESSION_CACHE_PREFIX}{user.id}",
        current_session_key,
        timeout=USER_SESSION_CACHE_TTL,
    )

    response = client.get("/health/live")

    assert response.status_code == 200
    assert UserActiveSession.objects.get(user=user).session_key == current_session_key
    assert client.session.get("_auth_user_id") == str(user.id)


@pytest.mark.django_db
def test_single_session_middleware_rechecks_db_when_verify_marker_cache_write_fails(
    client, django_user_model, monkeypatch
):
    user = django_user_model.objects.create_user(username="single_session_verify_fallback", password="pass123")
    client.force_login(user)
    current_session_key = client.session.session_key

    UserActiveSession.objects.filter(user=user).update(session_key="canonical-session-key")
    cache.set(
        f"{USER_SESSION_CACHE_PREFIX}{user.id}",
        current_session_key,
        timeout=USER_SESSION_CACHE_TTL,
    )

    original_add = cache.add

    def fake_add(key, value, timeout=None):
        if key.endswith(":verified"):
            raise RuntimeError("cache add down")
        return original_add(key, value, timeout=timeout)

    monkeypatch.setattr("core.middleware.single_session.cache.add", fake_add)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_single_session_middleware_keeps_session_when_authoritative_lookup_errors(
    client, django_user_model, monkeypatch
):
    user = django_user_model.objects.create_user(username="single_session_fail_open", password="pass123")
    client.force_login(user)
    current_session_key = client.session.session_key

    def fake_load_active_session_key(_user_id):
        raise DatabaseError("db unavailable")

    monkeypatch.setattr("core.middleware.single_session._load_active_session_key", fake_load_active_session_key)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert client.session.get("_auth_user_id") == str(user.id)
    assert client.session.session_key == current_session_key
