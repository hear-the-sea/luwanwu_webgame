import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import GameError
from gameplay.models import InventoryItem, ItemTemplate


@pytest.mark.django_db
class TestInventoryTreasuryMoves:
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
