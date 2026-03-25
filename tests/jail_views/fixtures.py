from __future__ import annotations

import pytest

from gameplay.services.manor.core import ensure_manor


@pytest.fixture
def authenticated_client_with_manor(client, django_user_model):
    user = django_user_model.objects.create_user(username="jail_view_user", password="pass12345")
    ensure_manor(user)
    client.force_login(user)
    return client
