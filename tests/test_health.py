import asyncio

import pytest
from django.test import override_settings

from core.views import health as health_views


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
    assert data["checks"] == {"db": True, "cache": True}


@pytest.mark.django_db
def test_health_ready_returns_503_when_db_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (False, "db fail"))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["checks"] == {"db": False, "cache": True}


@pytest.mark.django_db
def test_health_ready_returns_503_when_cache_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (False, "cache fail"))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["checks"] == {"db": True, "cache": False}


@pytest.mark.django_db
@override_settings(HEALTH_CHECK_CHANNEL_LAYER=True)
def test_health_ready_returns_503_when_channel_layer_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (False, "channel fail"))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["checks"]["channel_layer"] is False


@pytest.mark.django_db
@override_settings(HEALTH_CHECK_CELERY_BROKER=True)
def test_health_ready_returns_503_when_celery_broker_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (False, "broker fail"))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["checks"]["celery_broker"] is False


@pytest.mark.django_db
@override_settings(
    HEALTH_CHECK_CHANNEL_LAYER=True,
    HEALTH_CHECK_CELERY_BROKER=True,
    HEALTH_CHECK_CELERY_WORKERS=True,
    HEALTH_CHECK_CELERY_BEAT=True,
)
def test_health_ready_includes_async_worker_and_beat_checks(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_workers_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_beat_ready", lambda: (True, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["checks"]["celery_workers"] is True
    assert data["checks"]["celery_beat"] is True


@pytest.mark.django_db
@override_settings(
    HEALTH_CHECK_CHANNEL_LAYER=True,
    HEALTH_CHECK_CELERY_BROKER=True,
    HEALTH_CHECK_CELERY_ROUNDTRIP=True,
)
def test_health_ready_includes_celery_roundtrip_check(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_roundtrip_ready", lambda: (True, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["checks"]["celery_roundtrip"] is True


@pytest.mark.django_db
@override_settings(
    HEALTH_CHECK_CHANNEL_LAYER=True,
    HEALTH_CHECK_CELERY_BROKER=True,
    HEALTH_CHECK_CELERY_WORKERS=True,
    HEALTH_CHECK_CELERY_BEAT=True,
)
def test_health_ready_returns_503_when_celery_beat_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_workers_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_beat_ready", lambda: (False, "beat fail"))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["checks"]["celery_workers"] is True
    assert data["checks"]["celery_beat"] is False


@pytest.mark.django_db
@override_settings(
    HEALTH_CHECK_CHANNEL_LAYER=True,
    HEALTH_CHECK_CELERY_BROKER=True,
    HEALTH_CHECK_CELERY_ROUNDTRIP=True,
)
def test_health_ready_returns_503_when_celery_roundtrip_check_fails(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_channel_layer_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_broker_ready", lambda: (True, None))
    monkeypatch.setattr("core.views.health._check_celery_roundtrip_ready", lambda: (False, "roundtrip fail"))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["checks"]["celery_roundtrip"] is False


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_health_ready_hides_error_details_when_not_debug(monkeypatch, client):
    monkeypatch.setattr("core.views.health._check_database_ready", lambda: (False, None))
    monkeypatch.setattr("core.views.health._check_cache_ready", lambda: (False, None))

    resp = client.get("/health/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert "errors" not in data


@pytest.mark.django_db
@override_settings(HEALTH_CHECK_REQUIRE_INTERNAL=True)
def test_health_ready_rejects_public_requests(client):
    resp = client.get("/health/ready", REMOTE_ADDR="8.8.8.8")
    assert resp.status_code == 404


@pytest.mark.django_db
@override_settings(HEALTH_CHECK_REQUIRE_INTERNAL=True)
def test_health_ready_rejects_forwarded_requests_without_trusted_proxy(client):
    resp = client.get(
        "/health/ready",
        REMOTE_ADDR="10.0.0.2",
        HTTP_X_FORWARDED_FOR="8.8.8.8",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
@override_settings(HEALTH_CHECK_REQUIRE_INTERNAL=True, TRUSTED_PROXY_IPS=["10.0.0.0/8"])
def test_health_ready_allows_internal_request_via_trusted_proxy(client):
    resp = client.get(
        "/health/ready",
        REMOTE_ADDR="10.0.0.2",
        HTTP_X_FORWARDED_FOR="127.0.0.1",
    )
    assert resp.status_code == 200


@pytest.mark.django_db
@override_settings(DEBUG=True, HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS=0.1)
def test_health_channel_layer_check_times_out(monkeypatch):
    class SlowChannelLayer:
        async def new_channel(self, prefix):
            return f"{prefix}.test"

        async def send(self, channel_name, payload):
            return None

        async def receive(self, channel_name):
            await asyncio.sleep(0.2)
            return {"type": "health.ready", "marker": "ok"}

    monkeypatch.setattr("core.views.health.get_channel_layer", lambda: SlowChannelLayer())

    ok, error = health_views._check_channel_layer_ready()

    assert ok is False
    assert error is not None
    assert "timed out" in error
