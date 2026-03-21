"""
地图系统视图和 API 测试
"""

import json

import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import RaidRetreatStateError, RaidStartError, ScoutStartError
from gameplay.models import RaidRun
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
class TestMapViews:
    """地图系统视图测试"""

    def test_map_page(self, manor_with_user):
        """地图页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map"))
        assert response.status_code == 200
        assert "regions" in response.context

    def test_map_page_syncs_resources_before_loading_context(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        calls = {"prepared": 0, "context": 0}

        def _fake_context(*_args, **_kwargs):
            calls["context"] += 1
            return {
                "manor": manor,
                "selected_region": manor.region,
                "search_query": "",
                "protection_status": {},
                "active_raids": [],
                "active_scouts": [],
                "incoming_raids": [],
                "scout_count": 0,
                "player_troops": [],
            }

        monkeypatch.setattr(
            "gameplay.views.map.get_prepared_manor_for_read",
            lambda request, **_kwargs: calls.__setitem__("prepared", calls["prepared"] + 1) or manor,
        )
        monkeypatch.setattr("gameplay.views.map.get_map_context", _fake_context)

        response = client.get(reverse("gameplay:map"))
        assert response.status_code == 200
        assert calls == {"prepared": 1, "context": 1}

    def test_map_region_filter(self, manor_with_user):
        """地图地区过滤"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map") + "?region=beijing")
        assert response.status_code == 200
        assert response.context["selected_region"] == "beijing"


@pytest.mark.django_db
class TestMapAPI:
    """地图API测试"""

    def test_map_search_by_region(self, manor_with_user):
        """按地区搜索API"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map_search_api"), {"type": "region", "region": manor.region})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "results" in data

    def test_map_search_by_region_includes_self(self, manor_with_user):
        """按地区搜索应包含自己庄园，避免单人地区显示为空"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map_search_api"), {"type": "region", "region": manor.region})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        ids = {row.get("id") for row in data.get("results", [])}
        assert manor.id in ids

    def test_map_search_by_name(self, manor_with_user):
        """按名称搜索API"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:map_search_api"), {"type": "name", "q": "test"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_map_search_negative_page_clamped_to_one(self, manor_with_user):
        """地图搜索页码应限制为正整数"""
        manor, client = manor_with_user
        response = client.get(
            reverse("gameplay:map_search_api"),
            {"type": "region", "region": manor.region, "page": -5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["page"] == 1

    def test_protection_status_api(self, manor_with_user):
        """保护状态API"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:protection_status_api"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "protection" in data

    def test_raid_status_api(self, manor_with_user):
        """出征状态API"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:raid_status_api"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "active_raids" in data

    def test_raid_status_api_reads_status_without_triggering_refresh(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        calls = {"manor": 0, "refresh_activity": 0, "raids": 0, "scouts": 0, "incoming": 0}

        monkeypatch.setattr(
            "gameplay.views.map.get_manor",
            lambda user: calls.__setitem__("manor", calls["manor"] + 1) or manor,
        )
        monkeypatch.setattr(
            "gameplay.views.map.refresh_raid_activity",
            lambda *_args, **_kwargs: calls.__setitem__("refresh_activity", calls["refresh_activity"] + 1),
        )
        monkeypatch.setattr(
            "gameplay.views.map.get_active_raids",
            lambda current_manor: calls.__setitem__("raids", calls["raids"] + 1) or [],
        )
        monkeypatch.setattr(
            "gameplay.views.map.get_active_scouts",
            lambda current_manor: calls.__setitem__("scouts", calls["scouts"] + 1) or [],
        )
        monkeypatch.setattr(
            "gameplay.views.map.get_incoming_raids",
            lambda current_manor: calls.__setitem__("incoming", calls["incoming"] + 1) or [],
        )

        response = client.get(reverse("gameplay:raid_status_api"))

        assert response.status_code == 200
        assert calls == {"manor": 1, "refresh_activity": 0, "raids": 1, "scouts": 1, "incoming": 1}

    def test_refresh_raid_activity_api_refreshes_before_listing(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        calls: list[tuple[object, ...]] = []

        monkeypatch.setattr(
            "gameplay.views.map.get_manor",
            lambda user: calls.append(("manor", user)) or manor,
        )
        monkeypatch.setattr(
            "gameplay.views.map.refresh_raid_activity",
            lambda current_manor, *, prefer_async=False: calls.append(
                ("refresh_activity", current_manor, prefer_async)
            ),
        )
        monkeypatch.setattr(
            "gameplay.views.map.get_active_raids",
            lambda current_manor: calls.append(("raids", current_manor)) or [],
        )
        monkeypatch.setattr(
            "gameplay.views.map.get_active_scouts",
            lambda current_manor: calls.append(("scouts", current_manor)) or [],
        )
        monkeypatch.setattr(
            "gameplay.views.map.get_incoming_raids",
            lambda current_manor: calls.append(("incoming", current_manor)) or [],
        )

        response = client.post(reverse("gameplay:refresh_raid_activity_api"))

        assert response.status_code == 200
        assert calls[0][0] == "manor"
        assert calls[1:] == [
            ("refresh_activity", manor, True),
            ("raids", manor),
            ("scouts", manor),
            ("incoming", manor),
        ]
        data = response.json()
        assert data["success"] is True
        assert data["active_raids"] == []
        assert data["active_scouts"] == []
        assert data["incoming_raids"] == []

    def test_refresh_raid_activity_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"refresh": 0}

        monkeypatch.setattr("gameplay.views.map._acquire_map_action_lock", lambda *_a, **_k: (False, "", None))
        monkeypatch.setattr(
            "gameplay.views.map.refresh_raid_activity",
            lambda *_args, **_kwargs: called.__setitem__("refresh", called["refresh"] + 1),
        )

        response = client.post(reverse("gameplay:refresh_raid_activity_api"))

        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["refresh"] == 0

    def test_refresh_raid_activity_api_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.map.refresh_raid_activity",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy refresh")),
        )

        with pytest.raises(ValueError, match="legacy refresh"):
            client.post(reverse("gameplay:refresh_raid_activity_api"))

    def test_manor_detail_api(self, manor_with_user):
        """庄园详情API"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:manor_detail_api", kwargs={"manor_id": manor.id}))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "manor" in data

    def test_manor_detail_api_not_found(self, manor_with_user):
        """庄园详情API - 不存在"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:manor_detail_api", kwargs={"manor_id": 99999}))
        assert response.status_code == 404

    def test_start_scout_api_rejects_invalid_target_id(self, manor_with_user):
        """侦察API应拒绝非法目标ID"""
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
        """侦察API应拒绝非正整数目标ID"""
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
        """侦察API应拒绝非对象JSON"""
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
        """侦察API应拒绝非法UTF-8 JSON请求体"""
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

    def test_start_raid_api_rejects_invalid_target_id(self, manor_with_user):
        """进攻API应拒绝非法目标ID"""
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_raid_api"),
            data=json.dumps({"target_id": "abc", "guest_ids": [1], "troop_loadout": {}}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "参数无效" in payload["error"]

    @pytest.mark.parametrize("target_id", [0, -1])
    def test_start_raid_api_rejects_non_positive_target_id(self, manor_with_user, target_id):
        """进攻API应拒绝非正整数目标ID"""
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_raid_api"),
            data=json.dumps({"target_id": target_id, "guest_ids": [1], "troop_loadout": {}}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "参数无效" in payload["error"]

    def test_start_raid_api_rejects_non_object_json(self, manor_with_user):
        """进攻API应拒绝非对象JSON"""
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_raid_api"),
            data=json.dumps(["bad-shape"]),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "无效的请求数据" in payload["error"]

    def test_start_raid_api_rejects_invalid_utf8_json(self, manor_with_user):
        """进攻API应拒绝非法UTF-8 JSON请求体"""
        _manor, client = manor_with_user
        response = client.post(
            reverse("gameplay:start_raid_api"),
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

    def test_start_raid_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_lock_raid_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.map._acquire_map_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.map.start_raid", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_raid_api"),
            data=json.dumps({"target_id": defender.id, "guest_ids": [1], "troop_loadout": {}}),
            content_type="application/json",
        )
        assert response.status_code == 409
        payload = response.json()
        assert payload["success"] is False
        assert "请求处理中，请稍候重试" in payload["error"]
        assert called["count"] == 0

    def test_start_raid_api_known_error_returns_400(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_known_raid_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_raid",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RaidStartError("raid blocked")),
        )

        response = client.post(
            reverse("gameplay:start_raid_api"),
            data=json.dumps({"target_id": defender.id, "guest_ids": [1], "troop_loadout": {}}),
            content_type="application/json",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "raid blocked" in payload["error"]

    def test_start_raid_api_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_legacy_raid_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_raid",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy raid start")),
        )

        with pytest.raises(ValueError, match="legacy raid start"):
            client.post(
                reverse("gameplay:start_raid_api"),
                data=json.dumps({"target_id": defender.id, "guest_ids": [1], "troop_loadout": {}}),
                content_type="application/json",
            )

    def test_retreat_raid_api_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_lock_retreat_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=attacker, defender=defender, status=RaidRun.Status.MARCHING)
        called = {"count": 0}

        monkeypatch.setattr("gameplay.views.map._acquire_map_action_lock", lambda *_a, **_k: (False, "", None))

        def _unexpected_retreat(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.map.request_raid_retreat", _unexpected_retreat)

        response = client.post(reverse("gameplay:retreat_raid_api", kwargs={"raid_id": run.id}))
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

    def test_start_raid_api_database_error_returns_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_exc_raid_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_raid",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:start_raid_api"),
            data=json.dumps({"target_id": defender.id, "guest_ids": [1], "troop_loadout": {}}),
            content_type="application/json",
        )
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_start_raid_api_programming_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_runtime_raid_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_raid",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:start_raid_api"),
                data=json.dumps({"target_id": defender.id, "guest_ids": [1], "troop_loadout": {}}),
                content_type="application/json",
            )

    def test_retreat_raid_api_database_error_returns_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_exc_retreat_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=attacker, defender=defender, status=RaidRun.Status.MARCHING)

        monkeypatch.setattr(
            "gameplay.views.map.request_raid_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:retreat_raid_api", kwargs={"raid_id": run.id}))
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_retreat_raid_api_known_error_returns_400(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_known_retreat_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=attacker, defender=defender, status=RaidRun.Status.MARCHING)

        monkeypatch.setattr(
            "gameplay.views.map.request_raid_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RaidRetreatStateError("retreating")),
        )

        response = client.post(reverse("gameplay:retreat_raid_api", kwargs={"raid_id": run.id}))
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "已在撤退中" in payload["error"]

    def test_retreat_raid_api_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_legacy_retreat_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=attacker, defender=defender, status=RaidRun.Status.MARCHING)

        monkeypatch.setattr(
            "gameplay.views.map.request_raid_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy raid retreat")),
        )

        with pytest.raises(ValueError, match="legacy raid retreat"):
            client.post(reverse("gameplay:retreat_raid_api", kwargs={"raid_id": run.id}))

    def test_retreat_raid_api_programming_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_runtime_retreat_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=attacker, defender=defender, status=RaidRun.Status.MARCHING)

        monkeypatch.setattr(
            "gameplay.views.map.request_raid_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:retreat_raid_api", kwargs={"raid_id": run.id}))
