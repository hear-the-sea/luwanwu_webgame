"""
视图层和API端点测试
"""

import json

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from core.exceptions import GameError
from gameplay.models import InventoryItem, ItemTemplate, MissionRun, MissionTemplate, RaidRun, ScoutRecord
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
            "gameplay.services.inventory.consume_inventory_item_for_manor_locked",
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
            "gameplay.services.inventory.consume_inventory_item_for_manor_locked",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:use_mission_card"), {"mission_key": mission.key})


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

    def test_warehouse_page_projects_grain_item_without_writing_inventory(self, manor_with_user):
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
        assert warehouse_grain is None
        projected_entry = next(
            (entry for entry in response.context["inventory_items"] if entry.template.key == "grain"),
            None,
        )
        assert projected_entry is not None
        assert projected_entry.display_quantity == 777
        assert projected_entry.is_projected is True

    def test_warehouse_page_renders_soul_fusion_requirements_for_current_item(self, manor_with_user):
        manor, client = manor_with_user
        guest_template = GuestTemplate.objects.create(
            key="view_soul_fusion_guest",
            name="魂器候选门客",
            rarity=GuestRarity.BLUE,
            archetype=GuestArchetype.CIVIL,
            base_attack=100,
            base_intellect=140,
            base_defense=90,
            base_agility=95,
            base_luck=70,
            base_hp=1200,
            default_gender="male",
            default_morality=60,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.IDLE,
            level=66,
        )
        soul_container = ItemTemplate.objects.create(
            key="view_soul_fusion_container",
            name="蓝魂容器",
            effect_type=ItemTemplate.EffectType.TOOL,
            is_usable=True,
            effect_payload={
                "action": "soul_fusion",
                "min_level": 60,
                "allowed_rarities": ["blue", "purple"],
            },
        )
        InventoryItem.objects.create(
            manor=manor,
            template=soul_container,
            quantity=1,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )

        response = client.get(reverse("gameplay:warehouse"))

        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'data-soul-fusion-min-level="60"' in body
        assert 'data-soul-fusion-rarities="blue,purple"' in body
        assert f'data-guest-id="{guest.id}"' in body
        assert 'data-guest-level="66"' in body
        assert 'data-guest-rarity="blue"' in body

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

    def test_use_soul_container_rejects_non_positive_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_soul_container_item",
            name="灵魂容器",
            effect_payload={"action": "soul_fusion"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)
        called = {"count": 0}

        def _unexpected_call(*args, **kwargs):
            called["count"] += 1
            return {}

        monkeypatch.setattr("gameplay.views.inventory.use_soul_container", _unexpected_call)

        response = client.post(
            reverse("gameplay:use_soul_container", kwargs={"pk": item.pk}),
            {"guest_id": 0},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "请选择要融合的门客" in payload["error"]
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

    def test_use_item_ajax_database_error_returns_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="view_use_item_database_error", name="数据库异常道具")
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_inventory_item",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:use_item", kwargs={"pk": item.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 500
        payload = response.json()
        assert payload["success"] is False
        assert "操作失败，请稍后重试" in payload["error"]

    def test_use_item_ajax_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="view_use_item_runtime_error", name="运行时异常道具")
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_inventory_item",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:use_item", kwargs={"pk": item.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

    def test_use_rebirth_card_database_error_returns_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_rebirth_card_item_unexpected",
            name="门客重生卡异常",
            effect_payload={"action": "rebirth_guest"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_guest_rebirth_card",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
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

    def test_use_rebirth_card_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_rebirth_card_item_runtime",
            name="门客重生卡运行时异常",
            effect_payload={"action": "rebirth_guest"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_guest_rebirth_card",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:use_rebirth_card", kwargs={"pk": item.pk}),
                {"guest_id": 1},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

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

    def test_move_item_to_treasury_ajax_handles_database_error(self, manor_with_user, monkeypatch):
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
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
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

    def test_move_item_to_treasury_ajax_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="move_treasury_runtime_item", name="藏宝阁运行时异常道具")
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

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:move_to_treasury", kwargs={"pk": item.pk}),
                {"quantity": 2},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

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

    def test_upgrade_building_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        building = manor.buildings.first()

        monkeypatch.setattr(
            "gameplay.views.buildings.start_upgrade",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:dashboard")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_upgrade_building_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        building = manor.buildings.first()

        monkeypatch.setattr(
            "gameplay.views.buildings.start_upgrade",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:upgrade_building", kwargs={"pk": building.pk}))

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
