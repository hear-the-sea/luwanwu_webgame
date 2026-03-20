"""
任务系统视图测试
"""

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from core.exceptions import MissionDailyLimitError
from gameplay.models import MissionRun, MissionTemplate, ScoutRecord
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
class TestMissionViews:
    """任务系统视图测试"""

    def test_task_board_page(self, manor_with_user):
        """任务面板页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:tasks"))
        assert response.status_code == 200
        assert "missions" in response.context

    def test_task_board_tolerates_resource_sync_error(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.views.mission_page_context.project_resource_production_for_read",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("sync failed")),
        )

        response = client.get(reverse("gameplay:tasks"))
        assert response.status_code == 200
        assert "missions" in response.context

    def test_task_board_with_mission_selected(self, manor_with_user):
        """选择任务后的任务面板"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:tasks") + "?mission=huashan_lunjian")
        assert response.status_code == 200

    def test_accept_mission_rejects_missing_mission_key(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(reverse("gameplay:accept_mission"), {})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:tasks")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("请选择任务" in m for m in messages)

    def test_accept_mission_rejects_invalid_mission_key(self, manor_with_user):
        _manor, client = manor_with_user
        mission_key = "mission_not_exists_for_view_test"
        response = client.post(reverse("gameplay:accept_mission"), {"mission_key": mission_key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission_key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("任务不存在" in m for m in messages)

    def test_use_mission_card_rejects_missing_mission_key(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(reverse("gameplay:use_mission_card"), {})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:tasks")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("请选择任务" in m for m in messages)

    def test_use_mission_card_rejects_invalid_mission_key(self, manor_with_user):
        _manor, client = manor_with_user
        mission_key = "mission_not_exists_for_card_view_test"
        response = client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission_key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission_key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("任务不存在" in m for m in messages)

    def test_accept_mission_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_lock_conflict_{manor.id}",
            name="任务锁冲突",
            is_defense=True,
        )
        called = {"count": 0}

        monkeypatch.setattr(
            "gameplay.views.mission_helpers.acquire_mission_action_lock",
            lambda *_a, **_k: (False, "", None),
        )

        def _unexpected_launch(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.missions.launch_mission", _unexpected_launch)

        response = client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("任务请求处理中，请稍候重试" in m for m in messages)
        assert called["count"] == 0

    def test_use_mission_card_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_use_card_lock_conflict_{manor.id}",
            name="任务卡锁冲突",
        )
        called = {"count": 0}

        monkeypatch.setattr(
            "gameplay.views.mission_helpers.acquire_mission_action_lock",
            lambda *_a, **_k: (False, "", None),
        )

        def _unexpected_add(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.missions.add_mission_extra_attempt", _unexpected_add)

        response = client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("任务请求处理中，请稍候重试" in m for m in messages)
        assert called["count"] == 0

    def test_retreat_mission_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_retreat_lock_conflict_{manor.id}",
            name="撤退锁冲突任务",
            is_defense=False,
        )
        run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE)
        called = {"count": 0}

        monkeypatch.setattr(
            "gameplay.views.mission_helpers.acquire_mission_action_lock",
            lambda *_a, **_k: (False, "", None),
        )

        def _unexpected_retreat(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.missions.request_retreat", _unexpected_retreat)

        response = client.post(reverse("gameplay:mission_retreat", kwargs={"pk": run.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("任务请求处理中，请稍候重试" in m for m in messages)
        assert called["count"] == 0

    def test_retreat_scout_rejects_when_action_lock_conflicts(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"scout_def_lock_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        record = ScoutRecord.objects.create(
            attacker=attacker,
            defender=defender,
            status=ScoutRecord.Status.SCOUTING,
            complete_at=timezone.now(),
        )
        called = {"count": 0}

        monkeypatch.setattr(
            "gameplay.views.mission_helpers.acquire_mission_action_lock",
            lambda *_a, **_k: (False, "", None),
        )

        def _unexpected_retreat(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.raid.request_scout_retreat", _unexpected_retreat)

        response = client.post(reverse("gameplay:scout_retreat", kwargs={"pk": record.pk}))
        assert response.status_code == 302
        assert response.url == reverse("home")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("任务请求处理中，请稍候重试" in m for m in messages)
        assert called["count"] == 0

    def test_accept_mission_rejects_mixed_invalid_guest_ids(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_mission_invalid_guest_ids_{manor.id}",
            name="门客参数任务",
            is_defense=False,
            guest_only=True,
        )
        called = {"count": 0}

        def _unexpected_launch(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.missions.launch_mission", _unexpected_launch)

        response = client.post(
            reverse("gameplay:accept_mission"),
            {"mission_key": mission.key, "guest_ids": ["1", "abc"]},
        )

        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("门客选择有误" in m for m in messages)
        assert called["count"] == 0

    def test_accept_mission_rejects_invalid_troop_quantity(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_mission_invalid_troop_qty_{manor.id}",
            name="护院参数任务",
            is_defense=False,
            guest_only=False,
        )
        called = {"count": 0}

        def _unexpected_launch(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.missions.launch_mission", _unexpected_launch)
        monkeypatch.setattr("battle.troops.troop_template_list", lambda: [{"key": "archer"}])

        response = client.post(
            reverse("gameplay:accept_mission"),
            {"mission_key": mission.key, "guest_ids": ["1"], "troop_archer": "bad"},
        )

        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("护院配置有误" in m for m in messages)
        assert called["count"] == 0

    def test_accept_mission_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_unexpected_{manor.id}",
            name="异常任务",
            is_defense=True,
        )

        monkeypatch.setattr(
            "gameplay.views.missions.launch_mission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_accept_mission_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_runtime_{manor.id}",
            name="运行时任务",
            is_defense=True,
        )

        monkeypatch.setattr(
            "gameplay.views.missions.launch_mission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})

    def test_accept_mission_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_legacy_value_{manor.id}",
            name="旧异常任务",
            is_defense=True,
        )

        monkeypatch.setattr(
            "gameplay.views.missions.launch_mission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy mission error")),
        )

        with pytest.raises(ValueError, match="legacy mission error"):
            client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})

    def test_accept_mission_known_error_shows_message(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_known_{manor.id}",
            name="已知错误任务",
            is_defense=True,
        )

        monkeypatch.setattr(
            "gameplay.views.missions.launch_mission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(MissionDailyLimitError()),
        )

        response = client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("今日该任务次数已耗尽" in m for m in messages)

    def test_retreat_mission_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_retreat_unexpected_{manor.id}",
            name="撤退异常任务",
            is_defense=False,
        )
        run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE)

        monkeypatch.setattr(
            "gameplay.views.missions.request_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:mission_retreat", kwargs={"pk": run.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_retreat_mission_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_retreat_runtime_{manor.id}",
            name="撤退运行时任务",
            is_defense=False,
        )
        run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE)

        monkeypatch.setattr(
            "gameplay.views.missions.request_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:mission_retreat", kwargs={"pk": run.pk}))

    def test_retreat_mission_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_retreat_legacy_value_{manor.id}",
            name="撤退旧异常任务",
            is_defense=False,
        )
        run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE)

        monkeypatch.setattr(
            "gameplay.views.missions.request_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy retreat error")),
        )

        with pytest.raises(ValueError, match="legacy retreat error"):
            client.post(reverse("gameplay:mission_retreat", kwargs={"pk": run.pk}))

    def test_retreat_scout_database_error_does_not_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(username=f"scout_def_{attacker.id}", password="pass123")
        defender = ensure_manor(defender_user)
        record = ScoutRecord.objects.create(
            attacker=attacker,
            defender=defender,
            status=ScoutRecord.Status.SCOUTING,
            complete_at=timezone.now(),
        )

        monkeypatch.setattr(
            "gameplay.services.raid.request_scout_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:scout_retreat", kwargs={"pk": record.pk}))
        assert response.status_code == 302
        assert response.url == reverse("home")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_retreat_scout_programming_error_bubbles_up(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"scout_def_runtime_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        record = ScoutRecord.objects.create(
            attacker=attacker,
            defender=defender,
            status=ScoutRecord.Status.SCOUTING,
            complete_at=timezone.now(),
        )

        monkeypatch.setattr(
            "gameplay.services.raid.request_scout_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:scout_retreat", kwargs={"pk": record.pk}))

    def test_use_mission_card_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_use_card_unexpected_{manor.id}",
            name="任务卡异常任务",
        )

        monkeypatch.setattr(
            "gameplay.services.inventory.core.consume_inventory_item_for_manor_locked",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_use_mission_card_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_use_card_runtime_{manor.id}",
            name="任务卡运行时任务",
        )

        monkeypatch.setattr(
            "gameplay.services.inventory.core.consume_inventory_item_for_manor_locked",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission.key})

    def test_use_mission_card_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_use_card_legacy_value_{manor.id}",
            name="任务卡旧异常任务",
        )

        monkeypatch.setattr(
            "gameplay.services.inventory.core.consume_inventory_item_for_manor_locked",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            "gameplay.views.missions.add_mission_extra_attempt",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy mission card error")),
        )

        with pytest.raises(ValueError, match="legacy mission card error"):
            client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission.key})
