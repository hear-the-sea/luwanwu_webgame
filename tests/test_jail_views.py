"""
监牢与结义林视图测试
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import JailError, OathBondError
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
def test_jail_page_uses_explicit_read_helper(monkeypatch, authenticated_client_with_manor, django_user_model):
    client = authenticated_client_with_manor
    manor = ensure_manor(django_user_model.objects.get(username="jail_view_user"))
    calls = {"prepared": 0}

    monkeypatch.setattr(
        "gameplay.views.jail.get_prepared_manor_for_read",
        lambda request, **kwargs: calls.__setitem__("prepared", calls["prepared"] + 1) or manor,
    )
    monkeypatch.setattr(
        "gameplay.views.jail.get_jail_page_context",
        lambda current_manor: (
            {
                "jail_capacity": 0,
                "prisoners": [],
                "capture_rate_percent": 0,
                "recruit_loyalty_threshold": 0,
                "recruit_cost_gold_bar": 0,
            }
            if current_manor is manor
            else {}
        ),
    )

    response = client.get(reverse("gameplay:jail"))

    assert response.status_code == 200
    assert calls["prepared"] == 1


@pytest.mark.django_db
def test_jail_page_uses_selector_context(monkeypatch, authenticated_client_with_manor, django_user_model):
    client = authenticated_client_with_manor
    manor = ensure_manor(django_user_model.objects.get(username="jail_view_user"))
    calls = {"selector": 0}

    monkeypatch.setattr("gameplay.views.jail.get_prepared_manor_for_read", lambda request, **kwargs: manor)

    def _fake_selector(current_manor):
        calls["selector"] += 1
        assert current_manor is manor
        return {
            "jail_capacity": 3,
            "prisoners": [
                SimpleNamespace(
                    id=1,
                    display_name="prisoner-a",
                    guest_template=SimpleNamespace(rarity="green"),
                    loyalty=20,
                    original_manor=SimpleNamespace(display_name="旧主"),
                    captured_at=None,
                )
            ],
            "capture_rate_percent": 25,
            "recruit_loyalty_threshold": 30,
            "recruit_cost_gold_bar": 2,
        }

    monkeypatch.setattr("gameplay.views.jail.get_jail_page_context", _fake_selector)

    response = client.get(reverse("gameplay:jail"))

    assert response.status_code == 200
    assert calls["selector"] == 1
    assert response.context["prisoners"][0].display_name == "prisoner-a"


@pytest.mark.django_db
def test_oath_grove_page_uses_explicit_read_helper(monkeypatch, authenticated_client_with_manor, django_user_model):
    client = authenticated_client_with_manor
    manor = ensure_manor(django_user_model.objects.get(username="jail_view_user"))
    calls = {"prepared": 0}

    monkeypatch.setattr(
        "gameplay.views.jail.get_prepared_manor_for_read",
        lambda request, **kwargs: calls.__setitem__("prepared", calls["prepared"] + 1) or manor,
    )
    monkeypatch.setattr(
        "gameplay.views.jail.get_oath_grove_page_context",
        lambda current_manor: (
            {
                "oath_capacity": 0,
                "bonds": [],
                "available_guests": [],
            }
            if current_manor is manor
            else {}
        ),
    )

    response = client.get(reverse("gameplay:oath_grove"))

    assert response.status_code == 200
    assert calls["prepared"] == 1


@pytest.mark.django_db
def test_oath_grove_page_uses_selector_context(monkeypatch, authenticated_client_with_manor, django_user_model):
    client = authenticated_client_with_manor
    manor = ensure_manor(django_user_model.objects.get(username="jail_view_user"))
    calls = {"selector": 0}

    monkeypatch.setattr("gameplay.views.jail.get_prepared_manor_for_read", lambda request, **kwargs: manor)

    def _fake_selector(current_manor):
        calls["selector"] += 1
        assert current_manor is manor
        return {
            "oath_capacity": 5,
            "bonds": [
                SimpleNamespace(
                    guest_id=2,
                    guest=SimpleNamespace(display_name="bond-a", template=SimpleNamespace(rarity="blue"), level=9),
                    created_at=None,
                )
            ],
            "available_guests": [
                SimpleNamespace(id=3, display_name="guest-a", template=SimpleNamespace(rarity="green"), level=5)
            ],
        }

    monkeypatch.setattr("gameplay.views.jail.get_oath_grove_page_context", _fake_selector)

    response = client.get(reverse("gameplay:oath_grove"))

    assert response.status_code == 200
    assert calls["selector"] == 1
    assert response.context["bonds"][0].guest.display_name == "bond-a"


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

    def test_recruit_prisoner_api_known_game_error_returns_400(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.recruit_prisoner",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(JailError("prisoner blocked")),
        )

        response = client.post(reverse("gameplay:recruit_prisoner_api", kwargs={"prisoner_id": 1}))
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "prisoner blocked" in payload["error"]

    def test_recruit_prisoner_api_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.recruit_prisoner",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
        )

        with pytest.raises(ValueError, match="bad payload"):
            client.post(reverse("gameplay:recruit_prisoner_api", kwargs={"prisoner_id": 1}))

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

    def test_add_oath_bond_view_known_game_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OathBondError("bond blocked")),
        )

        response = client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:oath_grove")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("bond blocked" in m for m in messages)

    def test_add_oath_bond_view_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
        )

        with pytest.raises(ValueError, match="bad payload"):
            client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})

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
