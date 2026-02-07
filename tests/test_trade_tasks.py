from __future__ import annotations

import pytest
from django.utils import timezone

from trade.models import ShopStock
from trade.services.shop_config import ShopItemConfig
from trade.tasks import refresh_shop_stock


@pytest.mark.django_db
def test_refresh_shop_stock_creates_and_updates_daily_items(monkeypatch):
    today = timezone.now().date()

    config_list = [
        ShopItemConfig(item_key="daily_item", price=None, stock=5, daily_refresh=True),
        ShopItemConfig(item_key="no_refresh", price=None, stock=5, daily_refresh=False),
        ShopItemConfig(item_key="unlimited", price=None, stock=-1, daily_refresh=True),
    ]

    monkeypatch.setattr("trade.tasks.reload_shop_config", lambda: None)
    monkeypatch.setattr("trade.tasks.get_shop_config", lambda: list(config_list))

    result = refresh_shop_stock.run()
    assert result == "refreshed 1 items"

    stock = ShopStock.objects.get(item_key="daily_item")
    assert stock.current_stock == 5
    assert stock.last_refresh == today

    assert not ShopStock.objects.filter(item_key="no_refresh").exists()
    assert not ShopStock.objects.filter(item_key="unlimited").exists()


@pytest.mark.django_db
def test_refresh_shop_stock_returns_failure_summary(monkeypatch):
    config_list = [
        ShopItemConfig(item_key="ok", price=None, stock=2, daily_refresh=True),
        ShopItemConfig(item_key="bad", price=None, stock=2, daily_refresh=True),
    ]

    monkeypatch.setattr("trade.tasks.reload_shop_config", lambda: None)
    monkeypatch.setattr("trade.tasks.get_shop_config", lambda: list(config_list))

    original_update_or_create = ShopStock.objects.update_or_create

    def _update_or_create(*args, **kwargs):
        if kwargs.get("item_key") == "bad":
            raise RuntimeError("boom")
        return original_update_or_create(*args, **kwargs)

    monkeypatch.setattr(ShopStock.objects, "update_or_create", _update_or_create)

    result = refresh_shop_stock.run()
    assert result == "refreshed 1 items, 1 failed"

    assert ShopStock.objects.get(item_key="ok").current_stock == 2
