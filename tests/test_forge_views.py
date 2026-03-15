"""
锻造与铁匠铺视图测试
"""

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from gameplay.models import EquipmentProduction


@pytest.mark.django_db
class TestForgeViews:
    """锻造与铁匠铺视图测试"""

    def test_start_equipment_forging_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.start_equipment_forging",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
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
        _manor, client = manor_with_user
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
        _manor, client = manor_with_user

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

    def test_decompose_equipment_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.decompose_equipment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
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
        _manor, client = manor_with_user

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

    def test_synthesize_blueprint_equipment_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.forge.synthesize_equipment_with_blueprint",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
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
        _manor, client = manor_with_user
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
        _manor, client = manor_with_user
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
        _manor, client = manor_with_user

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
        _manor, client = manor_with_user

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
        _manor, client = manor_with_user

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
        _manor, client = manor_with_user

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
        _manor, client = manor_with_user

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
