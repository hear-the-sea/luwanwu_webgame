"""
仓库和物品管理视图测试
"""

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from core.exceptions import GameError, ItemNotUsableError
from gameplay.models import InventoryItem, ItemTemplate
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


@pytest.mark.django_db
class TestInventoryViews:
    """仓库系统视图测试"""

    def test_warehouse_page(self, manor_with_user):
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:warehouse"))
        assert response.status_code == 200
        assert "inventory_items" in response.context

    def test_warehouse_treasury_tab(self, manor_with_user):
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
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:recruitment_hall"))
        assert response.status_code == 200
        assert "pools" in response.context
        assert "candidates_payload" in response.context
        assert "candidate_count" in response.context
        assert "guests" not in response.context
        assert "capacity" not in response.context
        assert "available_gears" not in response.context

    def test_recruitment_hall_page_syncs_resources_before_loading_context(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        calls = {"sync": 0, "context": 0}

        def _fake_sync(*_args, **_kwargs):
            calls["sync"] += 1

        def _fake_context(*_args, **_kwargs):
            calls["context"] += 1
            return {
                "manor": manor,
                "pools": [],
                "candidates_payload": [],
                "candidate_count": 0,
                "records": [],
                "magnifying_glass_items": [],
            }

        monkeypatch.setattr("gameplay.views.inventory.project_resource_production_for_read", _fake_sync)
        monkeypatch.setattr("gameplay.views.inventory.get_recruitment_hall_context", _fake_context)

        response = client.get(reverse("gameplay:recruitment_hall"))
        assert response.status_code == 200
        assert calls == {"sync": 1, "context": 1}

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
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ItemNotUsableError("普通道具", message="use blocked")),
        )

        response = client.post(
            reverse("gameplay:use_item", kwargs={"pk": item.pk}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False
        assert "use blocked" in payload["error"]

    def test_use_item_ajax_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(key="view_use_item_legacy_error", name="旧式异常道具")
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_inventory_item",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy use blocked")),
        )

        with pytest.raises(ValueError, match="legacy use blocked"):
            client.post(
                reverse("gameplay:use_item", kwargs={"pk": item.pk}),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

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

    def test_use_rebirth_card_legacy_value_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        template = ItemTemplate.objects.create(
            key="view_rebirth_card_item_value_error",
            name="门客重生卡旧式异常",
            effect_payload={"action": "rebirth_guest"},
        )
        item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

        monkeypatch.setattr(
            "gameplay.views.inventory.use_guest_rebirth_card",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy rebirth")),
        )

        with pytest.raises(ValueError, match="legacy rebirth"):
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

        monkeypatch.setattr("gameplay.views.inventory.move_item_to_treasury", _unexpected_call)

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

        monkeypatch.setattr("gameplay.views.inventory.move_item_to_treasury", _fake_move)

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
            "gameplay.views.inventory.move_item_to_treasury",
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
            "gameplay.views.inventory.move_item_to_treasury",
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
            "gameplay.views.inventory.move_item_to_treasury",
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

        monkeypatch.setattr("gameplay.views.inventory.move_item_to_warehouse", _unexpected_call)

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

        monkeypatch.setattr("gameplay.views.inventory.move_item_to_warehouse", _fake_move)

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
