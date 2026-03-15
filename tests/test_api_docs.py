from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import clear_url_caches


@pytest.fixture(autouse=True)
def _clear_url_cache():
    clear_url_caches()
    yield
    clear_url_caches()


@pytest.mark.django_db
@override_settings(ENABLE_API_DOCS=False)
def test_api_docs_return_404_when_disabled(client):
    response = client.get("/api/docs/")
    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(ENABLE_API_DOCS=True, API_DOCS_REQUIRE_AUTH=True)
def test_api_schema_requires_authentication(client):
    response = client.get("/api/schema/")
    assert response.status_code in {401, 403}


@pytest.mark.django_db
@override_settings(ENABLE_API_DOCS=True, API_DOCS_REQUIRE_AUTH=True)
def test_api_schema_allows_authenticated_users(client, django_user_model):
    django_user_model.objects.create_user(username="docs_user", password="pass123")
    client.login(username="docs_user", password="pass123")

    response = client.get("/api/schema/")
    assert response.status_code == 200
