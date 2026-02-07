from __future__ import annotations

import pytest

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor import ensure_manor
from trade.models import ShopPurchaseLog, ShopSellLog, ShopStock
from trade.services.shop_config import ShopItemConfig
from trade.services.shop_service import (
    _get_category,
    _normalize_effect_type,
    buy_item,
    get_shop_items_for_display,
    sell_item,
)


@pytest.mark.django_db
def test_normalize_effect_type_and_category():
    assert _normalize_effect_type("manor_rename") == ItemTemplate.EffectType.TOOL
    assert _normalize_effect_type(ItemTemplate.EffectType.TOOL) == ItemTemplate.EffectType.TOOL
    assert _get_category("equip_weapon") == "武器"
    assert _get_category("unknown") == "其他"


@pytest.mark.django_db
def test_get_shop_items_for_display_uses_current_stock(monkeypatch):
    template = ItemTemplate.objects.create(
        key="shop_display_item",
        name="展示物品",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=False,
        price=12,
    )
    ShopStock.objects.create(item_key=template.key, current_stock=3)

    monkeypatch.setattr(
        "trade.services.shop_service.get_shop_config",
        lambda: [ShopItemConfig(item_key=template.key, price=None, stock=10, daily_refresh=False)],
    )

    items = get_shop_items_for_display()
    assert len(items) == 1
    assert items[0].key == template.key
    assert items[0].stock == 3
    assert items[0].available is True
    assert items[0].price == 12


@pytest.mark.django_db
def test_buy_item_decrements_stock_and_increments_inventory(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="shop_buy", password="pass12345")
    manor = ensure_manor(user)
    manor.silver = 1000
    manor.save(update_fields=["silver"])

    template = ItemTemplate.objects.create(
        key="shop_buy_item",
        name="购买物品",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=False,
        price=10,
    )

    config = ShopItemConfig(item_key=template.key, price=5, stock=4, daily_refresh=False)
    monkeypatch.setattr("trade.services.shop_service.get_shop_item_config", lambda *_args, **_kwargs: config)

    result = buy_item(manor, template.key, 2)
    assert result == {"item_name": template.name, "quantity": 2, "total_cost": 10}

    manor.refresh_from_db()
    assert manor.silver == 990

    stock = ShopStock.objects.get(item_key=template.key)
    assert stock.current_stock == 2

    inv = InventoryItem.objects.get(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert inv.quantity == 2

    log = ShopPurchaseLog.objects.get(manor=manor, item_key=template.key)
    assert log.quantity == 2
    assert log.unit_price == 5
    assert log.total_cost == 10


@pytest.mark.django_db
def test_sell_item_grants_silver_and_clears_zero_inventory(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="shop_sell", password="pass12345")
    manor = ensure_manor(user)
    manor.silver = 0
    manor.save(update_fields=["silver"])

    template = ItemTemplate.objects.create(
        key="shop_sell_item",
        name="出售物品",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=False,
        price=7,
    )

    config = ShopItemConfig(item_key=template.key, price=None, stock=-1, daily_refresh=False)
    monkeypatch.setattr("trade.services.shop_service.get_shop_item_config", lambda *_args, **_kwargs: config)

    InventoryItem.objects.create(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        quantity=1,
    )

    result = sell_item(manor, template.key, 1)
    assert result == {"item_name": template.name, "quantity": 1, "total_income": 7}

    manor.refresh_from_db()
    assert manor.silver == 7

    assert not InventoryItem.objects.filter(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()

    log = ShopSellLog.objects.get(manor=manor, item_key=template.key)
    assert log.quantity == 1
    assert log.unit_price == 7
    assert log.total_income == 7
