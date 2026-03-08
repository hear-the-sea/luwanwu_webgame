"""
视图层和API端点测试
"""

import json

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.exceptions import GameError
from gameplay.models import (
    EquipmentProduction,
    HorseProduction,
    InventoryItem,
    ItemTemplate,
    LivestockProduction,
    Message,
    MissionRun,
    MissionTemplate,
    RaidRun,
    ScoutRecord,
    SmeltingProduction,
    WorkAssignment,
    WorkTemplate,
)
from gameplay.services.manor.core import ensure_manor
from guests.models import (
    GearItem,
    GearSlot,
    GearTemplate,
    Guest,
    GuestArchetype,
    GuestRarity,
    GuestStatus,
    GuestTemplate,
)


@pytest.fixture
def authenticated_client(django_user_model):
    """返回已登录的测试客户端"""
    user = django_user_model.objects.create_user(username="testplayer", password="testpass123")
    client = Client()
    client.login(username="testplayer", password="testpass123")
    client.user = user
    return client


@pytest.fixture
def manor_with_user(authenticated_client):
    """返回带庄园的用户"""
    manor = ensure_manor(authenticated_client.user)
    return manor, authenticated_client


# ============ 核心页面测试 ============


@pytest.mark.django_db
class TestCoreViews:
    """核心页面视图测试"""

    def test_home_page_anonymous(self, client):
        """匿名用户访问首页"""
        response = client.get(reverse("home"))
        assert response.status_code == 200

    def test_home_page_authenticated(self, authenticated_client):
        """登录用户访问首页"""
        ensure_manor(authenticated_client.user)
        response = authenticated_client.get(reverse("home"))
        assert response.status_code == 200
        assert "manor" in response.context

    def test_dashboard_requires_login(self, client):
        """仪表盘需要登录"""
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 302  # 重定向到登录

    def test_dashboard_authenticated(self, manor_with_user):
        """登录用户访问仪表盘"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        assert "buildings" in response.context

    def test_dashboard_refresh_error_does_not_500(self, manor_with_user, monkeypatch):
        """状态刷新异常时仪表盘不应返回500。"""
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.views.core.refresh_manor_state",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        assert "操作失败，请稍后重试" in response.content.decode("utf-8")

    def test_authenticated_layout_contains_partial_nav_markers(self, manor_with_user):
        """认证页面应包含局部导航刷新容器与脚本。"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'id="main-nav"' in body
        assert 'id="info-bar"' in body
        assert 'id="page-shell"' in body
        assert 'id="page-extra-scripts"' in body
        assert "js/nav_partial.js" in body
        assert body.count('data-partial-nav="1"') >= 12
        assert f'href="{reverse("gameplay:warehouse")}" data-partial-nav="1"' in body
        assert f'href="{reverse("trade:trade")}" data-partial-nav="1"' in body

    def test_dashboard_upgrading_building_has_auto_refresh_countdown(self, manor_with_user):
        """建筑升级倒计时应携带自动刷新标记。"""
        manor, client = manor_with_user
        building = manor.buildings.select_related("building_type").first()
        assert building is not None
        building.is_upgrading = True
        building.upgrade_complete_at = timezone.now() + timezone.timedelta(minutes=5)
        building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

        response = client.get(
            reverse(
                "gameplay:buildings_category",
                kwargs={"category": building.building_type.category},
            )
        )
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'data-countdown="' in body
        assert 'data-refresh="1"' in body

    def test_settings_page(self, manor_with_user):
        """设置页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:settings"))
        assert response.status_code == 200

    def test_rename_manor_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.rename_manor",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("rename blocked")),
        )

        response = client.post(reverse("gameplay:rename_manor"), {"new_name": "新庄园名"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:settings")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("rename blocked" in m for m in messages)

    def test_rename_manor_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.rename_manor",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:rename_manor"), {"new_name": "新庄园名"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:settings")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_ranking_page(self, manor_with_user):
        """排行榜页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:ranking"))
        assert response.status_code == 200
        assert "ranking" in response.context


# ============ 任务系统测试 ============


@pytest.mark.django_db
class TestMissionViews:
    """任务系统视图测试"""

    def test_task_board_page(self, manor_with_user):
        """任务面板页面"""
        manor, client = manor_with_user
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

        monkeypatch.setattr("gameplay.views.missions._acquire_mission_action_lock", lambda *_a, **_k: (False, "", None))

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

        monkeypatch.setattr("gameplay.views.missions._acquire_mission_action_lock", lambda *_a, **_k: (False, "", None))

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

        monkeypatch.setattr("gameplay.views.missions._acquire_mission_action_lock", lambda *_a, **_k: (False, "", None))

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

        monkeypatch.setattr("gameplay.views.missions._acquire_mission_action_lock", lambda *_a, **_k: (False, "", None))

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

    def test_accept_mission_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_unexpected_{manor.id}",
            name="异常任务",
            is_defense=True,
        )

        monkeypatch.setattr(
            "gameplay.views.missions.launch_mission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_accept_mission_known_error_shows_message(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_accept_known_{manor.id}",
            name="已知错误任务",
            is_defense=True,
        )

        monkeypatch.setattr(
            "gameplay.views.missions.launch_mission",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("mission blocked")),
        )

        response = client.post(reverse("gameplay:accept_mission"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("mission blocked" in m for m in messages)

    def test_retreat_mission_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_retreat_unexpected_{manor.id}",
            name="撤退异常任务",
            is_defense=False,
        )
        run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE)

        monkeypatch.setattr(
            "gameplay.views.missions.request_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:mission_retreat", kwargs={"pk": run.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_retreat_scout_unexpected_error_does_not_500(self, manor_with_user, monkeypatch, django_user_model):
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
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:scout_retreat", kwargs={"pk": record.pk}))
        assert response.status_code == 302
        assert response.url == reverse("home")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_use_mission_card_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        mission = MissionTemplate.objects.create(
            key=f"view_use_card_unexpected_{manor.id}",
            name="任务卡异常任务",
        )

        monkeypatch.setattr(
            "gameplay.services.inventory.consume_inventory_item_for_manor_locked",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission.key})
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:tasks')}?mission={mission.key}"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)


# ============ 仓库系统测试 ============


@pytest.mark.django_db
class TestInventoryViews:
    """仓库系统视图测试"""

    def test_warehouse_page(self, manor_with_user):
        """仓库页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:warehouse"))
        assert response.status_code == 200
        assert "inventory_items" in response.context

    def test_warehouse_treasury_tab(self, manor_with_user):
        """仓库藏宝阁标签页"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:warehouse") + "?tab=treasury")
        assert response.status_code == 200
        assert response.context["current_tab"] == "treasury"

    def test_warehouse_page_syncs_grain_item_with_manor_grain(self, manor_with_user):
        manor, client = manor_with_user
        grain_template, _ = ItemTemplate.objects.get_or_create(
            key="grain",
            defaults={"name": "粮食"},
        )
        if not grain_template.name:
            grain_template.name = "粮食"
            grain_template.save(update_fields=["name"])

        manor.grain = 777
        manor.resource_updated_at = timezone.now()
        manor.save(update_fields=["grain", "resource_updated_at"])
        InventoryItem.objects.filter(
            manor=manor,
            template=grain_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        ).delete()

        response = client.get(reverse("gameplay:warehouse"))
        assert response.status_code == 200

        warehouse_grain = InventoryItem.objects.filter(
            manor=manor,
            template=grain_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        ).first()
        assert warehouse_grain is not None
        assert warehouse_grain.quantity == 777

    def test_recruitment_hall_page(self, manor_with_user):
        """招募大厅页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:recruitment_hall"))
        assert response.status_code == 200
        assert "pools" in response.context
        assert "candidates_payload" in response.context
        assert "candidate_count" in response.context
        assert "guests" not in response.context
        assert "capacity" not in response.context
        assert "available_gears" not in response.context

    def test_use_rebirth_card_rejects_non_positive_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_rebirth_card_item",
            name="门客重生卡",
            effect_payload={"action": "rebirth_guest"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1
            return {}

        monkeypatch.setattr("gameplay.views.inventory.use_guest_rebirth_card", _unexpected_call)

        response = client.post(
            reverse("gameplay:use_rebirth_card", kwargs={"pk": item.pk}),
            {"guest_id": -1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请选择要重生的门客" in payload["error"]
        assert called["count"] == 0

    def test_use_xisuidan_rejects_non_positive_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_xisuidan_item",
            name="洗髓丹",
            effect_payload={"action": "reroll_growth"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1
            return {}

        monkeypatch.setattr("gameplay.views.inventory.use_xisuidan", _unexpected_call)

        response = client.post(
            reverse("gameplay:use_xisuidan", kwargs={"pk": item.pk}),
            {"guest_id": -1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请选择要洗髓的门客" in payload["error"]
        assert called["count"] == 0

    def test_use_xidianka_rejects_non_positive_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_xidianka_item",
            name="洗点卡",
            effect_payload={"action": "reset_allocation"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1
            return {}

        monkeypatch.setattr("gameplay.views.inventory.use_xidianka", _unexpected_call)

        response = client.post(
            reverse("gameplay:use_xidianka", kwargs={"pk": item.pk}),
            {"guest_id": -1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请选择要洗点的门客" in payload["error"]
        assert called["count"] == 0

    def test_use_guest_rarity_upgrade_rejects_non_positive_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_rarity_upgrade_item",
            name="《上将的自我修养》残卷1",
            effect_payload={"action": "upgrade_guest_rarity"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1
            return {}

        monkeypatch.setattr("gameplay.views.inventory.use_guest_rarity_upgrade_item", _unexpected_call)

        response = client.post(
            reverse("gameplay:use_guest_rarity_upgrade", kwargs={"pk": item.pk}),
            {"guest_id": -1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请选择要升阶的门客" in payload["error"]
        assert called["count"] == 0

    def test_use_item_ajax_handles_known_error(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="view_use_item_known_error", name="普通道具")
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_inventory_item",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("use blocked")),
        )

        response = client.post(
            reverse("gameplay:use_item", kwargs={"pk": item.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "use blocked" in payload["error"]

    def test_use_rebirth_card_unexpected_error_returns_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_rebirth_card_item_unexpected",
            name="门客重生卡异常",
            effect_payload={"action": "rebirth_guest"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_guest_rebirth_card",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:use_rebirth_card", kwargs={"pk": item.pk}),
            {"guest_id": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_unequip_view_rejects_invalid_guest_id(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("guests:unequip"),
            {"guest": "abc", "gear": []},
        )
        assert response.status_code == 302
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("参数错误" in m for m in messages)

    def test_unequip_view_rejects_invalid_gear_ids(self, manor_with_user):
        manor, client = manor_with_user
        guest_template = GuestTemplate.objects.create(
            key=f"view_unequip_invalid_gear_guest_tpl_{manor.id}",
            name="卸装门客模板",
            archetype=GuestArchetype.CIVIL,
            rarity=GuestRarity.GRAY,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.IDLE,
        )

        response = client.post(
            reverse("guests:unequip"),
            {"guest": str(guest.pk), "gear": ["abc"]},
        )
        assert response.status_code == 302
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("装备选择有误" in m for m in messages)

    def test_dismiss_guest_allows_injured_status_and_returns_equipped_gear(self, manor_with_user):
        manor, client = manor_with_user
        guest_template = GuestTemplate.objects.create(
            key=f"view_dismiss_injured_guest_tpl_{manor.id}",
            name="重伤辞退门客模板",
            archetype=GuestArchetype.CIVIL,
            rarity=GuestRarity.GRAY,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.INJURED,
        )
        gear_template = GearTemplate.objects.create(
            key=f"view_dismiss_injured_gear_tpl_{manor.id}",
            name="重伤辞退测试装备",
            slot=GearSlot.WEAPON,
            rarity=GuestRarity.GRAY,
        )
        item_template = ItemTemplate.objects.create(
            key=gear_template.key,
            name="重伤辞退测试装备道具",
            effect_type=ItemTemplate.EffectType.TOOL,
            effect_payload={},
            is_usable=True,
        )
        GearItem.objects.create(manor=manor, template=gear_template, guest=guest)

        response = client.post(reverse("guests:dismiss", kwargs={"pk": guest.pk}))

        assert response.status_code == 302
        assert response.url == reverse("guests:roster")
        assert not Guest.objects.filter(pk=guest.pk).exists()
        returned_item = InventoryItem.objects.get(
            manor=manor,
            template=item_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        assert returned_item.quantity == 1
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("已辞退" in m for m in messages)

    def test_move_item_to_treasury_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_treasury_item", name="藏宝阁测试道具")
        item = InventoryItem.objects.create(
            manor=manor,
            template=template,
            quantity=5,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.move_item_to_treasury", _unexpected_call)

        response = client.post(
            reverse("gameplay:move_to_treasury", kwargs={"pk": item.pk}),
            {"quantity": -3},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "数量参数无效" in payload["error"]
        assert called["count"] == 0

    def test_move_item_to_treasury_ajax_success(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_treasury_success_item", name="藏宝阁成功道具")
        item = InventoryItem.objects.create(
            manor=manor,
            template=template,
            quantity=5,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        called = {"args": None}

        def _fake_move(manor_arg, item_id_arg, quantity_arg):
            called["args"] = (manor_arg.id, item_id_arg, quantity_arg)

        monkeypatch.setattr("gameplay.services.move_item_to_treasury", _fake_move)

        response = client.post(
            reverse("gameplay:move_to_treasury", kwargs={"pk": item.pk}),
            {"quantity": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert "移动到藏宝阁" in payload["message"]
        assert called["args"] == (manor.id, item.pk, 2)

    def test_move_item_to_treasury_ajax_handles_game_error(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_treasury_game_error_item", name="藏宝阁业务异常道具")
        item = InventoryItem.objects.create(
            manor=manor,
            template=template,
            quantity=5,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )

        monkeypatch.setattr(
            "gameplay.services.move_item_to_treasury",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(GameError("藏宝阁空间不足")),
        )

        response = client.post(
            reverse("gameplay:move_to_treasury", kwargs={"pk": item.pk}),
            {"quantity": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "藏宝阁空间不足" in payload["error"]

    def test_move_item_to_treasury_ajax_handles_unexpected_error(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_treasury_unexpected_item", name="藏宝阁未知异常道具")
        item = InventoryItem.objects.create(
            manor=manor,
            template=template,
            quantity=5,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )

        monkeypatch.setattr(
            "gameplay.services.move_item_to_treasury",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:move_to_treasury", kwargs={"pk": item.pk}),
            {"quantity": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_move_item_to_warehouse_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_warehouse_item", name="仓库测试道具")
        item = InventoryItem.objects.create(
            manor=manor,
            template=template,
            quantity=5,
            storage_location=InventoryItem.StorageLocation.TREASURY,
        )
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.move_item_to_warehouse", _unexpected_call)

        response = client.post(
            reverse("gameplay:move_to_warehouse", kwargs={"pk": item.pk}),
            {"quantity": -3},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "数量参数无效" in payload["error"]
        assert called["count"] == 0

    def test_move_item_to_warehouse_ajax_success(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_warehouse_success_item", name="仓库成功道具")
        item = InventoryItem.objects.create(
            manor=manor,
            template=template,
            quantity=5,
            storage_location=InventoryItem.StorageLocation.TREASURY,
        )
        called = {"args": None}

        def _fake_move(manor_arg, item_id_arg, quantity_arg):
            called["args"] = (manor_arg.id, item_id_arg, quantity_arg)

        monkeypatch.setattr("gameplay.services.move_item_to_warehouse", _fake_move)

        response = client.post(
            reverse("gameplay:move_to_warehouse", kwargs={"pk": item.pk}),
            {"quantity": 3},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert "移动到仓库" in payload["message"]
        assert called["args"] == (manor.id, item.pk, 3)


# ============ 消息系统测试 ============


@pytest.mark.django_db
class TestMessageViews:
    """消息系统视图测试"""

    def test_messages_page(self, manor_with_user):
        """消息列表页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:messages"))
        assert response.status_code == 200
        assert "message_list" in response.context

    def test_mark_all_read(self, manor_with_user):
        """标记全部已读"""
        manor, client = manor_with_user
        response = client.post(reverse("gameplay:mark_all_messages_read"))
        assert response.status_code == 302  # 重定向回消息列表

    def test_claim_attachment_handles_game_error(self, manor_with_user):
        """领取无附件消息时应优雅失败而不是500。"""
        manor, client = manor_with_user
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.SYSTEM,
            title="无附件测试",
            attachments={},
        )

        response = client.post(reverse("gameplay:claim_attachment", kwargs={"pk": message.pk}))

        assert response.status_code == 302

    def test_claim_attachment_json_success(self, manor_with_user):
        """JSON 请求领取附件成功返回结构化结果。"""
        manor, client = manor_with_user
        ItemTemplate.objects.create(key="msg_json_item", name="测试道具")
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.REWARD,
            title="json附件",
            attachments={"items": {"msg_json_item": 2}},
        )

        response = client.post(
            reverse("gameplay:claim_attachment", kwargs={"pk": message.pk}),
            HTTP_ACCEPT="application/json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["message_id"] == message.pk
        assert payload["claimed"][0]["kind"] == "item"

    def test_claim_attachment_json_error(self, manor_with_user):
        """JSON 请求领取无附件时返回400错误。"""
        manor, client = manor_with_user
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.SYSTEM,
            title="json无附件",
            attachments={},
        )

        response = client.post(
            reverse("gameplay:claim_attachment", kwargs={"pk": message.pk}),
            HTTP_ACCEPT="application/json",
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert payload["message_id"] == message.pk
        assert "error" in payload

    def test_view_message_json_tolerates_unread_count_failure(self, manor_with_user, monkeypatch):
        """JSON 查看消息时 unread 计数失败应降级为0而不是500。"""
        manor, client = manor_with_user
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.SYSTEM,
            title="json unread fallback",
            attachments={},
        )

        monkeypatch.setattr(
            "gameplay.views.messages.unread_message_count",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
        )

        response = client.get(
            reverse("gameplay:view_message", kwargs={"pk": message.pk}),
            HTTP_ACCEPT="application/json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["message_id"] == message.pk
        assert payload["unread_count"] == 0

    def test_claim_attachment_json_error_tolerates_unread_count_failure(self, manor_with_user, monkeypatch):
        """JSON 领取附件失败时 unread 计数异常不应扩大为500。"""
        manor, client = manor_with_user
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.SYSTEM,
            title="json claim unread fallback",
            attachments={},
        )

        monkeypatch.setattr(
            "gameplay.views.messages.unread_message_count",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
        )

        response = client.post(
            reverse("gameplay:claim_attachment", kwargs={"pk": message.pk}),
            HTTP_ACCEPT="application/json",
        )

        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert payload["message_id"] == message.pk
        assert payload["unread_count"] == 0

    def test_claim_attachment_json_unexpected_error_tolerates_unread_count_failure(self, manor_with_user, monkeypatch):
        """JSON 领取附件异常时 unread 计数失败也应降级返回。"""
        manor, client = manor_with_user
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.REWARD,
            title="json claim unexpected unread fallback",
            attachments={"items": {"msg_json_item_unexpected": 1}},
        )

        monkeypatch.setattr(
            "gameplay.views.messages.claim_message_attachments",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(
            "gameplay.views.messages.unread_message_count",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
        )

        response = client.post(
            reverse("gameplay:claim_attachment", kwargs={"pk": message.pk}),
            HTTP_ACCEPT="application/json",
        )

        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert payload["message_id"] == message.pk
        assert payload["unread_count"] == 0
        assert "操作失败，请稍后重试" in payload["error"]

    def test_claim_attachment_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        """普通表单领取附件异常时应降级为消息提示。"""
        manor, client = manor_with_user
        message = Message.objects.create(
            manor=manor,
            kind=Message.Kind.REWARD,
            title="claim unexpected fallback",
            attachments={"items": {"msg_item_unexpected": 1}},
        )

        monkeypatch.setattr(
            "gameplay.views.messages.claim_message_attachments",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:claim_attachment", kwargs={"pk": message.pk}))

        assert response.status_code == 302
        assert response.url == reverse("gameplay:view_message", kwargs={"pk": message.pk})
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)


# ============ 科技系统测试 ============


@pytest.mark.django_db
class TestTechnologyViews:
    """科技系统视图测试"""

    def test_technology_page(self, manor_with_user):
        """科技页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology"))
        assert response.status_code == 200
        assert "technologies" in response.context

    def test_technology_martial_tab(self, manor_with_user):
        """武艺科技标签页"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology") + "?tab=martial")
        assert response.status_code == 200
        assert response.context["current_tab"] == "martial"

    def test_technology_invalid_tab_falls_back_to_basic(self, manor_with_user):
        """非法科技标签页应回退到基础分类。"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology") + "?tab=unknown")
        assert response.status_code == 200
        assert response.context["current_tab"] == "basic"

    def test_upgrade_technology_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "basic"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:technology')}?tab=basic"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_upgrade_technology_redirects_to_safe_next_url(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: {"message": "ok"},
        )
        next_url = f"{reverse('gameplay:technology')}?tab=martial&troop=dao#tech-dao_attack"

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "basic", "next": next_url},
        )
        assert response.status_code == 302
        assert response.url == next_url

    def test_upgrade_technology_rejects_unsafe_next_url(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: {"message": "ok"},
        )

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "martial", "troop": "dao", "next": "https://evil.example/phish"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:technology')}?tab=martial&troop=dao"


# ============ 生产系统测试 ============


@pytest.mark.django_db
class TestProductionViews:
    """生产系统视图测试"""

    def test_stable_page(self, manor_with_user):
        """马房页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:stable"))
        assert response.status_code == 200
        assert "horse_options" in response.context

    def test_stable_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        HorseProduction.objects.create(
            manor=manor,
            horse_key="test_horse",
            horse_name="测试马",
            quantity=1,
            grain_cost=10,
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=HorseProduction.Status.PRODUCING,
        )

        response = client.get(reverse("gameplay:stable"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_ranch_page(self, manor_with_user):
        """畜牧场页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:ranch"))
        assert response.status_code == 200
        assert "livestock_options" in response.context

    def test_ranch_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        LivestockProduction.objects.create(
            manor=manor,
            livestock_key="test_livestock",
            livestock_name="测试家畜",
            quantity=1,
            grain_cost=8,
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=LivestockProduction.Status.PRODUCING,
        )

        response = client.get(reverse("gameplay:ranch"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_smithy_page(self, manor_with_user):
        """冶炼坊页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:smithy"))
        assert response.status_code == 200
        assert "metal_options" in response.context

    def test_smithy_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        SmeltingProduction.objects.create(
            manor=manor,
            metal_key="test_metal",
            metal_name="测试物品",
            quantity=1,
            cost_type="silver",
            cost_amount=10,
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=SmeltingProduction.Status.PRODUCING,
        )

        response = client.get(reverse("gameplay:smithy"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_start_horse_production_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.start_horse_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:start_horse_production"), {"horse_key": "any", "quantity": "1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:stable")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_horse_production_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.start_horse_production", _unexpected_start)

        response = client.post(reverse("gameplay:start_horse_production"), {"horse_key": "any", "quantity": "-1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:stable")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_horse_production_rejects_missing_horse_key(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.start_horse_production", _unexpected_start)

        response = client.post(reverse("gameplay:start_horse_production"), {"quantity": "1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:stable")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("请选择马匹类型" in m for m in messages)
        assert called["count"] == 0

    def test_start_livestock_production_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.ranch.start_livestock_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:start_livestock_production"), {"livestock_key": "any", "quantity": "1"}
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:ranch")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_livestock_production_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.ranch.start_livestock_production", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_livestock_production"),
            {"livestock_key": "any", "quantity": "bad"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:ranch")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_smelting_production_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.smithy.start_smelting_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:start_smelting_production"), {"metal_key": "any", "quantity": "1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:smithy")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_smelting_production_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.smithy.start_smelting_production", _unexpected_start)

        response = client.post(reverse("gameplay:start_smelting_production"), {"metal_key": "any", "quantity": "0"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:smithy")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_equipment_forging_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=synthesize&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_equipment_forging_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.forge.start_equipment_forging", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"equipment_key": "equip_dummy", "quantity": "bad", "category": "helmet", "mode": "synthesize"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=synthesize&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_equipment_forging_rejects_missing_equipment_key(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.forge.start_equipment_forging", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_equipment_forging"),
            {"quantity": "1", "category": "helmet", "mode": "invalid"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=synthesize&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("请选择装备类型" in m for m in messages)
        assert called["count"] == 0

    def test_forge_page(self, manor_with_user):
        """铁匠铺页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:forge"))
        assert response.status_code == 200
        assert "equipment_list" in response.context
        assert "device" in response.context["equipment_categories"]

    def test_forge_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        EquipmentProduction.objects.create(
            manor=manor,
            equipment_key="test_equipment",
            equipment_name="测试装备",
            quantity=1,
            material_costs={"iron": 1},
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=EquipmentProduction.Status.FORGING,
        )

        response = client.get(reverse("gameplay:forge"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_decompose_equipment_view_redirects_with_category(self, manor_with_user, monkeypatch):
        """分解装备后返回当前分类。"""
        manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_a, **_k: {
                "equipment_key": "equip_dummy",
                "equipment_name": "测试装备",
                "quantity": 2,
                "rewards": {},
            },
        )

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "2", "category": "helmet"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=decompose&category=helmet"

    def test_decompose_equipment_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "1", "category": "helmet", "mode": "decompose"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=decompose&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_decompose_equipment_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_decompose(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.forge.decompose_equipment", _unexpected_decompose)

        response = client.post(
            reverse("gameplay:decompose_equipment"),
            data={"equipment_key": "equip_dummy", "quantity": "-1", "category": "helmet", "mode": "decompose"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=decompose&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_synthesize_blueprint_equipment_view_redirects_with_category(self, manor_with_user, monkeypatch):
        """图纸合成后返回当前分类。"""
        manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_a, **_k: {
                "blueprint_key": "bp_dummy",
                "result_key": "equip_dummy",
                "result_name": "测试装备",
                "quantity": 1,
                "craft_times": 1,
            },
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=synthesize&category=helmet"

    def test_synthesize_blueprint_equipment_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "1", "category": "helmet", "mode": "synthesize"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=synthesize&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_synthesize_blueprint_equipment_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_synthesize(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            _unexpected_synthesize,
        )

        response = client.post(
            reverse("gameplay:synthesize_blueprint_equipment"),
            data={"blueprint_key": "bp_dummy", "quantity": "bad", "category": "helmet", "mode": "synthesize"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:forge')}?mode=synthesize&category=helmet"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_forge_decompose_mode_uses_shared_category_filter(self, manor_with_user, monkeypatch):
        """分解模式应复用装备分类筛选。"""
        manor, client = manor_with_user
        captured = {}

        monkeypatch.setattr("gameplay.services.buildings.forge.get_equipment_options", lambda *_a, **_k: [])

        def _mock_get_decomposable(_manor, category=None):
            captured["category"] = category
            return []

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_decomposable_equipment_options", _mock_get_decomposable
        )

        response = client.get(reverse("gameplay:forge") + "?mode=decompose&category=helmet")
        assert response.status_code == 200
        assert response.context["current_mode"] == "decompose"
        assert response.context["current_category"] == "helmet"
        assert captured["category"] == "helmet"

    def test_forge_decompose_mode_merges_weapon_categories(self, manor_with_user, monkeypatch):
        """分解模式下剑刀枪弓鞭应统一映射为武器分类。"""
        manor, client = manor_with_user
        captured = {}

        monkeypatch.setattr("gameplay.services.buildings.forge.get_equipment_options", lambda *_a, **_k: [])

        def _mock_get_decomposable(_manor, category=None):
            captured["category"] = category
            return []

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_decomposable_equipment_options", _mock_get_decomposable
        )

        response = client.get(reverse("gameplay:forge") + "?mode=decompose&category=sword")
        assert response.status_code == 200
        assert response.context["current_mode"] == "decompose"
        assert response.context["current_category"] == "weapon"
        assert captured["category"] == "weapon"

    def test_forge_decompose_mode_paginates_to_nine_items(self, manor_with_user, monkeypatch):
        """分解模式每页最多展示9项。"""
        manor, client = manor_with_user

        monkeypatch.setattr("gameplay.services.buildings.forge.get_equipment_options", lambda *_a, **_k: [])
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_decomposable_equipment_options",
            lambda *_a, **_k: [
                {
                    "key": f"equip_{i}",
                    "name": f"装备{i}",
                    "rarity": "green",
                    "rarity_label": "绿色",
                    "quantity": 1,
                    "effect_type": "equip_weapon",
                    "category": "weapon",
                    "category_name": "武器",
                }
                for i in range(10)
            ],
        )

        response = client.get(reverse("gameplay:forge") + "?mode=decompose&category=all")
        assert response.status_code == 200
        decompose_page_obj = response.context["decompose_page_obj"]
        assert len(decompose_page_obj.object_list) == 9
        assert decompose_page_obj.has_next()

    def test_forge_synthesize_mode_merges_weapon_categories(self, manor_with_user, monkeypatch):
        """合成模式下剑刀枪弓鞭也应归并到武器分类。"""
        manor, client = manor_with_user

        def _item(key: str, category: str) -> dict:
            return {
                "key": key,
                "name": key,
                "category": category,
                "category_name": category,
                "materials": [],
                "base_duration": 120,
                "actual_duration": 120,
                "can_afford": True,
                "required_forging": 1,
                "is_unlocked": True,
                "max_quantity": 1,
                "is_forging": False,
            }

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_equipment_options",
            lambda *_a, **_k: [
                _item("equip_a", "sword"),
                _item("equip_b", "dao"),
                _item("equip_c", "helmet"),
            ],
        )
        monkeypatch.setattr("gameplay.services.buildings.forge.get_blueprint_synthesis_options", lambda *_a, **_k: [])
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_decomposable_equipment_options", lambda *_a, **_k: []
        )

        response = client.get(reverse("gameplay:forge") + "?mode=synthesize&category=sword")
        assert response.status_code == 200
        assert response.context["current_mode"] == "synthesize"
        assert response.context["current_category"] == "weapon"
        page_obj = response.context["equipment_list"]
        assert {item["key"] for item in page_obj.object_list} == {"equip_a", "equip_b"}

    def test_forge_synthesize_mode_supports_device_blueprint_category(self, manor_with_user, monkeypatch):
        """合成模式应支持器械分类筛选图纸卡片。"""
        manor, client = manor_with_user

        monkeypatch.setattr("gameplay.services.buildings.forge.get_equipment_options", lambda *_a, **_k: [])
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_decomposable_equipment_options", lambda *_a, **_k: []
        )
        monkeypatch.setattr(
            "gameplay.services.buildings.forge.get_blueprint_synthesis_options",
            lambda *_a, **_k: [
                {
                    "blueprint_key": "bp_device",
                    "blueprint_name": "器械图纸",
                    "blueprint_count": 1,
                    "result_key": "equip_unknown_device",
                    "result_name": "器械产物",
                    "result_effect_type": "equip_device",
                    "result_quantity": 1,
                    "required_forging": 1,
                    "description": "",
                    "costs": [],
                    "max_synthesis_quantity": 1,
                    "is_unlocked": True,
                    "can_afford": True,
                    "can_synthesize": True,
                },
                {
                    "blueprint_key": "bp_helmet",
                    "blueprint_name": "头盔图纸",
                    "blueprint_count": 1,
                    "result_key": "equip_unknown_helmet",
                    "result_name": "头盔产物",
                    "result_effect_type": "equip_helmet",
                    "result_quantity": 1,
                    "required_forging": 1,
                    "description": "",
                    "costs": [],
                    "max_synthesis_quantity": 1,
                    "is_unlocked": True,
                    "can_afford": True,
                    "can_synthesize": True,
                },
            ],
        )

        response = client.get(reverse("gameplay:forge") + "?mode=synthesize&category=device")
        assert response.status_code == 200
        assert response.context["current_mode"] == "synthesize"
        assert response.context["current_category"] == "device"
        options = response.context["blueprint_synthesis_options"]
        assert len(options) == 1
        assert options[0]["blueprint_key"] == "bp_device"
        assert options[0]["result_category"] == "device"

    def test_forge_all_category_prioritizes_forgeable_high_requirement(self, manor_with_user, monkeypatch):
        """全部分类下：可锻造优先，且高需求等级优先。"""
        manor, client = manor_with_user

        def _item(key: str, required_forging: int, is_unlocked: bool, can_afford: bool) -> dict:
            return {
                "key": key,
                "name": key,
                "category": "helmet",
                "category_name": "头盔",
                "materials": [],
                "base_duration": 120,
                "actual_duration": 120,
                "can_afford": can_afford,
                "required_forging": required_forging,
                "is_unlocked": is_unlocked,
                "max_quantity": 1,
                "is_forging": False,
            }

        mocked_options = [
            _item("unaffordable_r10", 10, True, False),
            _item("forgeable_r5", 5, True, True),
            _item("locked_r9", 9, False, True),
            _item("forgeable_r7", 7, True, True),
            _item("forgeable_r1", 1, True, True),
        ]

        monkeypatch.setattr("gameplay.services.buildings.forge.get_equipment_options", lambda *_a, **_k: mocked_options)

        response = client.get(reverse("gameplay:forge") + "?category=all")
        assert response.status_code == 200

        page_obj = response.context["equipment_list"]
        ordered_keys = [item["key"] for item in page_obj.object_list]
        assert ordered_keys == ["forgeable_r7", "forgeable_r5", "forgeable_r1", "unaffordable_r10", "locked_r9"]

    def test_forge_specific_category_prioritizes_forgeable_high_requirement(self, manor_with_user, monkeypatch):
        """分类标签下：可锻造优先，且高需求等级优先。"""
        manor, client = manor_with_user

        def _item(key: str, required_forging: int, is_unlocked: bool, can_afford: bool) -> dict:
            return {
                "key": key,
                "name": key,
                "category": "helmet",
                "category_name": "头盔",
                "materials": [],
                "base_duration": 120,
                "actual_duration": 120,
                "can_afford": can_afford,
                "required_forging": required_forging,
                "is_unlocked": is_unlocked,
                "max_quantity": 1,
                "is_forging": False,
            }

        mocked_options = [
            _item("unaffordable_r10", 10, True, False),
            _item("forgeable_r3", 3, True, True),
            _item("locked_r9", 9, False, True),
            _item("forgeable_r7", 7, True, True),
        ]

        def _mock_get_equipment_options(*_args, **kwargs):
            assert kwargs.get("category") == "helmet"
            return mocked_options

        monkeypatch.setattr("gameplay.services.buildings.forge.get_equipment_options", _mock_get_equipment_options)

        response = client.get(reverse("gameplay:forge") + "?category=helmet")
        assert response.status_code == 200

        page_obj = response.context["equipment_list"]
        ordered_keys = [item["key"] for item in page_obj.object_list]
        assert ordered_keys == ["forgeable_r7", "forgeable_r3", "unaffordable_r10", "locked_r9"]


# ============ 打工系统测试 ============


@pytest.mark.django_db
class TestWorkViews:
    """打工系统视图测试"""

    @staticmethod
    def _create_work_data(manor, suffix: str) -> tuple[Guest, WorkTemplate]:
        guest_template = GuestTemplate.objects.create(
            key=f"view_work_guest_tpl_{suffix}_{manor.id}",
            name=f"打工门客模板{suffix}",
            archetype=GuestArchetype.CIVIL,
            rarity=GuestRarity.GRAY,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.IDLE,
        )
        work_template = WorkTemplate.objects.create(
            key=f"view_work_template_{suffix}_{manor.id}",
            name=f"打工模板{suffix}",
            required_level=1,
            required_force=0,
            required_intellect=0,
            reward_silver=100,
            work_duration=3600,
        )
        return guest, work_template

    def test_work_page(self, manor_with_user):
        """打工页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:work"))
        assert response.status_code == 200
        assert "works" in response.context

    def test_work_page_shows_assignment_in_matching_work_card(self, manor_with_user):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "inline_assignment")
        WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.WORKING,
            complete_at=timezone.now() + timezone.timedelta(minutes=30),
        )

        response = client.get(reverse("gameplay:work"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "执行门客" in body
        assert guest.display_name in body
        assert "打工中 (" not in body

    def test_work_tier_filter(self, manor_with_user):
        """打工等级过滤"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:work") + "?tier=senior")
        assert response.status_code == 200
        assert response.context["current_tier"] == "senior"

    def test_assign_work_known_error_shows_message(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "assign_known")

        monkeypatch.setattr(
            "gameplay.views.work.assign_guest_to_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("work blocked")),
        )

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": guest.id, "work_key": work_template.key},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("work blocked" in m for m in messages)

    def test_assign_work_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "assign_exc")

        monkeypatch.setattr(
            "gameplay.views.work.assign_guest_to_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": guest.id, "work_key": work_template.key},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_assign_work_rejects_invalid_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        _guest, work_template = self._create_work_data(manor, "invalid_guest_id")
        called = {"count": 0}

        def _unexpected_assign(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.work.assign_guest_to_work", _unexpected_assign)

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": "abc", "work_key": work_template.key},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("参数错误" in m for m in messages)
        assert called["count"] == 0

    def test_recall_work_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "recall_exc")
        assignment = WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.WORKING,
            complete_at=timezone.now(),
        )

        monkeypatch.setattr(
            "gameplay.views.work.recall_guest_from_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:recall_work", kwargs={"pk": assignment.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_claim_work_reward_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "claim_exc")
        assignment = WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.COMPLETED,
            complete_at=timezone.now(),
        )

        monkeypatch.setattr(
            "gameplay.views.work.claim_work_reward",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:claim_work_reward", kwargs={"pk": assignment.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)


# ============ 募兵系统测试 ============


@pytest.mark.django_db
class TestRecruitmentViews:
    """募兵系统视图测试"""

    def test_troop_recruitment_page(self, manor_with_user):
        """募兵页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:troop_recruitment"))
        assert response.status_code == 200
        assert "recruitment_options" in response.context

    def test_troop_recruitment_page_category_filter(self, manor_with_user):
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:troop_recruitment") + "?category=jian")
        assert response.status_code == 200
        assert response.context["current_category"] == "jian"
        assert "recruitment_categories" in response.context
        options = response.context["recruitment_options"]
        assert options
        assert all(option.get("troop_class") == "jian" for option in options)

    def test_start_troop_recruitment_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.recruitment.recruitment.start_troop_recruitment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(
            reverse("gameplay:start_troop_recruitment"),
            {"troop_key": "any", "quantity": "1"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:troop_recruitment")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_troop_recruitment_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.recruitment.recruitment.start_troop_recruitment", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_troop_recruitment"),
            {"troop_key": "any", "quantity": "bad"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:troop_recruitment")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_troop_recruitment_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.recruitment.recruitment.start_troop_recruitment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("recruit blocked")),
        )

        response = client.post(
            reverse("gameplay:start_troop_recruitment"),
            {"troop_key": "any", "quantity": "1"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:troop_recruitment")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("recruit blocked" in m for m in messages)


# ============ 地图系统测试 ============


@pytest.mark.django_db
class TestMapViews:
    """地图系统视图测试"""

    def test_map_page(self, manor_with_user):
        """地图页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map"))
        assert response.status_code == 200
        assert "regions" in response.context

    def test_map_region_filter(self, manor_with_user):
        """地图地区过滤"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map") + "?region=beijing")
        assert response.status_code == 200
        assert response.context["selected_region"] == "beijing"


# ============ API 测试 ============


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
        manor, client = manor_with_user
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
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:protection_status_api"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "protection" in data

    def test_raid_status_api(self, manor_with_user):
        """出征状态API"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:raid_status_api"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "active_raids" in data

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
        manor, client = manor_with_user
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
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("raid blocked")),
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

    def test_start_scout_api_unexpected_error_returns_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_exc_scout_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_scout",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
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

    def test_start_raid_api_unexpected_error_returns_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_exc_raid_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)

        monkeypatch.setattr(
            "gameplay.views.map.start_raid",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
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

    def test_retreat_raid_api_unexpected_error_returns_500(self, manor_with_user, monkeypatch, django_user_model):
        attacker, client = manor_with_user
        defender_user = django_user_model.objects.create_user(
            username=f"map_exc_retreat_def_{attacker.id}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=attacker, defender=defender, status=RaidRun.Status.MARCHING)

        monkeypatch.setattr(
            "gameplay.views.map.request_raid_retreat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:retreat_raid_api", kwargs={"raid_id": run.id}))
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]


# ============ POST 操作测试 ============


@pytest.mark.django_db
class TestPostOperations:
    """POST操作测试"""

    def test_upgrade_building(self, manor_with_user):
        """建筑升级"""
        manor, client = manor_with_user
        manor.grain = manor.silver = 100000
        manor.save()
        building = manor.buildings.first()
        response = client.post(reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}))
        assert response.status_code == 302  # 重定向

    def test_upgrade_building_known_error_shows_message(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        building = manor.buildings.first()

        monkeypatch.setattr(
            "gameplay.views.buildings.start_upgrade",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("upgrade blocked")),
        )

        response = client.post(reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("upgrade blocked" in m for m in messages)

    def test_upgrade_building_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        building = manor.buildings.first()

        monkeypatch.setattr(
            "gameplay.views.buildings.start_upgrade",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_upgrade_building_redirects_to_safe_next_url(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        building = manor.buildings.first()

        monkeypatch.setattr(
            "gameplay.views.buildings.start_upgrade",
            lambda *_args, **_kwargs: None,
        )
        next_url = f"{reverse('gameplay:dashboard')}#building-{building.pk}"

        response = client.post(
            reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}),
            {"next": next_url},
        )
        assert response.status_code == 302
        assert response.url == next_url

    def test_upgrade_building_rejects_unsafe_next_url(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        building = manor.buildings.first()

        monkeypatch.setattr(
            "gameplay.views.buildings.start_upgrade",
            lambda *_args, **_kwargs: None,
        )

        response = client.post(
            reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}),
            {"next": "https://evil.example/phish"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")

    def test_delete_messages_empty(self, manor_with_user):
        """删除消息 - 空选择"""
        manor, client = manor_with_user
        response = client.post(reverse("gameplay:delete_messages"))
        assert response.status_code == 302


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

    def test_recruit_prisoner_api_unexpected_error_returns_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.recruit_prisoner",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:recruit_prisoner_api", kwargs={"prisoner_id": 1}))
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]


@pytest.mark.django_db
class TestJailAndOathViews:
    """监牢与结义林页面操作测试"""

    def test_add_oath_bond_view_unexpected_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.jail.add_oath_bond",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        response = client.post(reverse("gameplay:add_oath_bond_view"), {"guest_id": 1})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:oath_grove")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)


# ============ 权限测试 ============


@pytest.mark.django_db
class TestPermissions:
    """权限测试"""

    def test_protected_pages_redirect(self, client):
        """受保护页面重定向到登录"""
        protected_urls = [
            reverse("gameplay:dashboard"),
            reverse("gameplay:tasks"),
            reverse("gameplay:warehouse"),
            reverse("gameplay:messages"),
            reverse("gameplay:technology"),
            reverse("gameplay:work"),
            reverse("gameplay:stable"),
            reverse("gameplay:map"),
        ]
        for url in protected_urls:
            response = client.get(url)
            assert response.status_code == 302, f"{url} should redirect"

    def test_api_requires_login(self, client):
        """API需要登录"""
        api_urls = [
            reverse("gameplay:map_search_api"),
            reverse("gameplay:raid_status_api"),
            reverse("gameplay:protection_status_api"),
        ]
        for url in api_urls:
            response = client.get(url)
            assert response.status_code == 302, f"{url} should redirect"
