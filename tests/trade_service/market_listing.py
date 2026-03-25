from __future__ import annotations

import pytest

from core.exceptions import TradeValidationError
from gameplay.models import InventoryItem
from trade.models import MarketListing
from trade.services import market_service

pytest_plugins = ("tests.trade_service.fixtures",)


@pytest.mark.django_db
class TestMarketListing:
    def test_create_listing_success(self, seller_manor, tradeable_item_template):
        initial_silver = seller_manor.silver
        initial_quantity = InventoryItem.objects.get(
            manor=seller_manor, template=tradeable_item_template, storage_location="warehouse"
        ).quantity

        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        assert listing is not None
        assert listing.quantity == 10
        assert listing.unit_price == 2000
        assert listing.total_price == 20000
        assert listing.status == MarketListing.Status.ACTIVE

        seller_manor.refresh_from_db()
        assert seller_manor.silver == initial_silver - market_service.LISTING_FEES[7200]

        inventory = InventoryItem.objects.filter(
            manor=seller_manor, template=tradeable_item_template, storage_location="warehouse"
        ).first()
        assert inventory.quantity == initial_quantity - 10

    def test_create_listing_untradeable_item(self, seller_manor, untradeable_item_template):
        InventoryItem.objects.create(
            manor=seller_manor,
            template=untradeable_item_template,
            quantity=10,
            storage_location="warehouse",
        )

        with pytest.raises(TradeValidationError, match="不可交易"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_untradeable_item",
                quantity=5,
                unit_price=1000,
                duration=7200,
            )

    def test_create_listing_insufficient_quantity(self, seller_manor):
        with pytest.raises(TradeValidationError, match="数量不足"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=1000,
                unit_price=2000,
                duration=7200,
            )

    def test_create_listing_insufficient_silver(self, seller_manor):
        seller_manor.silver = 100
        seller_manor.save()

        with pytest.raises(TradeValidationError, match="银两不足"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=10,
                unit_price=2000,
                duration=7200,
            )

    def test_create_listing_price_too_low(self, seller_manor, tradeable_item_template):
        with pytest.raises(TradeValidationError, match="不能低于"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=10,
                unit_price=500,
                duration=7200,
            )
