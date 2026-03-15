"""
监牢与结义林视图测试
"""

from __future__ import annotations

import json

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
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


@pytest.mark.django_db
class TestJailAndOathAPI:
    """监牢与结义林 API 测试"""

    def test_add_oath_bond_api_rejects_non_object_json(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:add_oath_bond_api"),
            data=json.dumps(["bad-shape"]),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    def test_add_oath_bond_api_rejects_invalid_utf8_json(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:add_oath_bond_api"),
            data=b"\xff",
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    @pytest.mark.parametrize("guest_id", [0, -1])
    def test_add_oath_bond_api_rejects_non_positive_guest_id(self, manor_with_user, guest_id):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:add_oath_bond_api"),
            data=json.dumps({"guest_id": guest_id}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请指定门客" in payload["error"]

    def test_remove_oath_bond_api_rejects_non_object_json(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:remove_oath_bond_api"),
            data=json.dumps(["bad-shape"]),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    def test_remove_oath_bond_api_rejects_invalid_utf8_json(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:remove_oath_bond_api"),
            data=b"\xff",
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    @pytest.mark.parametrize("guest_id", [0, -1])
    def test_remove_oath_bond_api_rejects_non_positive_guest_id(self, manor_with_user, guest_id):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:remove_oath_bond_api"),
            data=json.dumps({"guest_id": guest_id}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请指定门客" in payload["error"]

    def test_recruit_prisoner_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_recruit(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.recruit_prisoner", _unexpected_recruit)

        response = client.post(reverse("gameplay:recruit_prisoner_api", kwargs={"prisoner_id": 1}))
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_draw_pie_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_draw(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.draw_pie", _unexpected_draw)

        response = client.post(reverse("gameplay:draw_pie_api", kwargs={"prisoner_id": 1}))
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_release_prisoner_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_release(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.release_prisoner", _unexpected_release)

        response = client.post(reverse("gameplay:release_prisoner_api", kwargs={"prisoner_id": 1}))
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_add_oath_bond_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_add(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.add_oath_bond", _unexpected_add)

        response = client.post(
            reverse("gameplay:add_oath_bond_api"),
            data=json.dumps({"guest_id": 1}),
            content_type="application/json",
        )
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_remove_oath_bond_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_remove(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.remove_oath_bond", _unexpected_remove)

        response = client.post(
            reverse("gameplay:remove_oath_bond_api"),
            data=json.dumps({"guest_id": 1}),
            content_type="application/json",
        )
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_recruit_prisoner_api_database_error_returns_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.recruit_prisoner",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:recruit_prisoner_api", kwargs={"prisoner_id": 1}))
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_recruit_prisoner_api_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.recruit_prisoner",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:recruit_prisoner_api", kwargs={"prisoner_id": 1}))


@pytest.mark.django_db
class TestJailAndOathViews:
    """监牢与结义林页面操作测试"""

    def test_recruit_prisoner_view_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.jail._acquire_jail_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_recruit(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.jail.recruit_prisoner", _unexpected_recruit)

        response = client.post(reverse("gameplay:recruit_prisoner_view", kwargs={"prisoner_id": 1}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:jail")
        messages = list(get_messages(response.wsgi_request))
        assert any(
            message.level_tag == "warning" and "请求处理中，请稍候重试" in message.message for message in messages
        )
        assert called["count"] == 0

    def test_add_oath_bond_view_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:oath_grove")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_add_oath_bond_view_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})

    def test_remove_oath_bond_view_uses_error_message_when_guest_not_bonded(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr("gameplay.views.jail.remove_oath_bond", lambda *_args, **_kwargs: 0)

        response = client.post(reverse("gameplay:remove_oath_bond_view", kwargs={"guest_id": 1}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:oath_grove")
        messages = list(get_messages(response.wsgi_request))
        assert any(message.level_tag == "error" and "该门客未结义" in message.message for message in messages)
