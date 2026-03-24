from __future__ import annotations

import pytest

from gameplay.models import InventoryItem
from trade.services import market_service

pytest_plugins = ("tests.trade_service.conftest",)


@pytest.mark.django_db
class TestMarketQueries:
    def test_get_active_listings(self, seller_manor):
        for index in range(3):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=10,
                unit_price=2000 + index * 100,
                duration=7200,
            )

        listings = market_service.get_active_listings()
        assert listings.count() == 3

    def test_get_my_listings(self, seller_manor):
        market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        my_listings = market_service.get_my_listings(seller_manor)
        assert my_listings.count() == 1

    def test_get_tradeable_inventory(self, seller_manor, tradeable_item_template, untradeable_item_template):
        InventoryItem.objects.create(
            manor=seller_manor,
            template=untradeable_item_template,
            quantity=10,
            storage_location="warehouse",
        )

        tradeable = market_service.get_tradeable_inventory(seller_manor)
        assert tradeable.count() == 1
        assert tradeable.first().template == tradeable_item_template
