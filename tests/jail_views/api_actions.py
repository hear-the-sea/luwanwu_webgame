from __future__ import annotations

import json

import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import JailError


@pytest.mark.django_db
class TestJailAndOathAPI:
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
