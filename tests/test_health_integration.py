from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_health_ready_with_external_services(require_env_services, client):
    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["db"] is True
    assert payload["checks"]["cache"] is True
    assert payload["checks"]["channel_layer"] is True
    assert payload["checks"]["celery_broker"] is True
