import pytest
from django.test import override_settings


@pytest.mark.django_db
def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.django_db
def test_health_ready(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["db"] is True
    assert data["checks"]["cache"] is True
    assert data["checks"]["channel_layer"] is True
    assert data["checks"]["celery_broker"] is True


@pytest.mark.django_db
def test_health_ready_returns_503_when_db_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (False, "db fail"))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["checks"]["db"] is False
    assert data["checks"]["cache"] is True
    assert data["checks"]["channel_layer"] is True
    assert data["checks"]["celery_broker"] is True


@pytest.mark.django_db
def test_health_ready_returns_503_when_cache_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (False, "cache fail"))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["checks"]["db"] is True
    assert data["checks"]["cache"] is False
    assert data["checks"]["channel_layer"] is True
    assert data["checks"]["celery_broker"] is True


@pytest.mark.django_db
def test_health_ready_returns_503_when_channel_layer_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (False, "channel fail"))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["checks"]["channel_layer"] is False
    assert data["checks"]["celery_broker"] is True


@pytest.mark.django_db
def test_health_ready_returns_503_when_celery_broker_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (False, "broker fail"))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["checks"]["channel_layer"] is True
    assert data["checks"]["celery_broker"] is False


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_health_ready_hides_error_details_when_not_debug(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (False, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (False, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (False, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (False, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert "errors" not in data
