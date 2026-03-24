"""
地图侦察 API 测试
"""

import json

import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import ScoutStartError
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
class TestMapScoutAPI:
    def test_start_scout_api_rejects_invalid_target_id(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=json.dumps({"target_id": "abc"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "参数无效" in payload["error"]

    def test_start_scout_api_target_lookup_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.map.ManorModel.objects.get",
            lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad manor lookup")),
        )

        with pytest.raises(ValueError, match="bad manor lookup"):
            client.post(
                reverse("gameplay:start_scout_api"),
                data=json.dumps({"target_id": 1}),
                content_type="application/json",
            )

    @pytest.mark.parametrize("target_id", [0, -1])
    def test_start_scout_api_rejects_non_positive_target_id(self, manor_with_user, target_id):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=json.dumps({"target_id": target_id}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "参数无效" in payload["error"]

    def test_start_scout_api_rejects_non_object_json(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=json.dumps(["bad-shape"]),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    def test_start_scout_api_rejects_invalid_utf8_json(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=b"\xff",
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    def test_start_scout_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_lock_scout_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.map._acquire_map_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.map.start_scout", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=json.dumps({"target_id": defender.id}),
            content_type="application/json",
        )
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_start_scout_api_database_error_returns_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_exc_scout_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_scout",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=json.dumps({"target_id": defender.id}),
            content_type="application/json",
        )
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_start_scout_api_known_error_returns_400(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_known_scout_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_scout",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ScoutStartError("scout blocked")),
        )

        response = client.post(
            reverse("gameplay:start_scout_api"),
            data=json.dumps({"target_id": defender.id}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "scout blocked" in payload["error"]

    def test_start_scout_api_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_legacy_scout_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_scout",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy scout start")),
        )

        with pytest.raises(ValueError, match="legacy scout start"):
            client.post(
                reverse("gameplay:start_scout_api"),
                data=json.dumps({"target_id": defender.id}),
                content_type="application/json",
            )

    def test_start_scout_api_programming_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_runtime_scout_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_scout",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:start_scout_api"),
                data=json.dumps({"target_id": defender.id}),
                content_type="application/json",
            )
