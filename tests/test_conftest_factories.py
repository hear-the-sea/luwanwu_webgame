from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_user_factory_creates_distinct_users(user_factory):
    user_a = user_factory()
    user_b = user_factory()

    assert user_a.pk != user_b.pk
    assert user_a.username != user_b.username


@pytest.mark.django_db
def test_auth_client_factory_returns_logged_in_client(auth_client_factory):
    client, user = auth_client_factory(username="factory_client_user", password="factory-pass-123")

    response = client.get("/")

    assert response.wsgi_request.user.is_authenticated is True
    assert response.wsgi_request.user.pk == user.pk


@pytest.mark.django_db
def test_manor_factory_creates_manor_for_user(manor_factory):
    manor, user = manor_factory(username="factory_manor_user")

    assert manor.user_id == user.id
