from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from gameplay.services.manor.core import ensure_manor


@pytest.fixture
def authenticated_client_with_manor(client, django_user_model):
    user = django_user_model.objects.create_user(username="jail_view_user", password="pass12345")
    ensure_manor(user)
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_recruit_prisoner_view_rejects_when_action_lock_conflicts(monkeypatch, authenticated_client_with_manor):
    client = authenticated_client_with_manor
    called = {"count": 0}

    monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

    def _unexpected_recruit(*_args, **_kwargs):
        called["count"] += 1

    monkeypatch.setattr("gameplay.views.jail.recruit_prisoner", _unexpected_recruit)

    response = client.post(reverse("gameplay:recruit_prisoner_view", kwargs={"prisoner_id": 1}))
    assert response.status_code == 302
    assert response.url == reverse("gameplay:jail")
    messages = list(get_messages(response.wsgi_request))
    assert any(message.level_tag == "warning" and "请求处理中，请稍候重试" in message.message for message in messages)
    assert called["count"] == 0


@pytest.mark.django_db
def test_remove_oath_bond_view_uses_error_message_when_guest_not_bonded(monkeypatch, authenticated_client_with_manor):
    client = authenticated_client_with_manor
    monkeypatch.setattr("gameplay.views.jail.remove_oath_bond", lambda *_args, **_kwargs: 0)

    response = client.post(reverse("gameplay:remove_oath_bond_view", kwargs={"guest_id": 1}))
    assert response.status_code == 302
    assert response.url == reverse("gameplay:oath_grove")
    messages = list(get_messages(response.wsgi_request))
    assert any(message.level_tag == "error" and "该门客未结义" in message.message for message in messages)
