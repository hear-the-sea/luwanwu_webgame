import pytest
from django.db import transaction

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from gameplay.services.manor.treasury import move_item_to_treasury, move_item_to_warehouse


@pytest.mark.django_db
def test_move_item_to_treasury_rejects_non_positive_quantity(django_user_model):
    user = django_user_model.objects.create_user(username="treasury_move_qty_non_positive", password="pass123")
    manor = ensure_manor(user)

    template = ItemTemplate.objects.create(key="treasury_move_qty_item", name="契约测试物品")
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=3,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    with transaction.atomic(), pytest.raises(AssertionError, match="requires positive quantity"):
        move_item_to_treasury(manor, item.id, 0)


@pytest.mark.django_db
def test_move_item_to_warehouse_rejects_non_positive_quantity(django_user_model):
    user = django_user_model.objects.create_user(username="warehouse_move_qty_non_positive", password="pass123")
    manor = ensure_manor(user)

    template = ItemTemplate.objects.create(key="warehouse_move_qty_item", name="契约测试物品")
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=3,
        storage_location=InventoryItem.StorageLocation.TREASURY,
    )

    with transaction.atomic(), pytest.raises(AssertionError, match="requires positive quantity"):
        move_item_to_warehouse(manor, item.id, -1)
