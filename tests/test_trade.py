"""
交易系统测试
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from gameplay.models import InventoryItem, ItemTemplate, Manor
from trade.models import MarketListing, MarketTransaction
from trade.services import market_service


@pytest.fixture
def tradeable_item_template(db):
    """创建可交易的物品模板"""
    template, _ = ItemTemplate.objects.get_or_create(
        key="test_tradeable_item",
        defaults={
            "name": "测试可交易物品",
            "effect_type": "none",
            "tradeable": True,
            "price": 1000,
        },
    )
    return template


@pytest.fixture
def untradeable_item_template(db):
    """创建不可交易的物品模板"""
    template, _ = ItemTemplate.objects.get_or_create(
        key="test_untradeable_item",
        defaults={
            "name": "测试不可交易物品",
            "effect_type": "none",
            "tradeable": False,
            "price": 500,
        },
    )
    return template


@pytest.fixture
def seller_manor(django_user_model, tradeable_item_template):
    """创建卖家庄园，拥有物品和银两"""
    user = django_user_model.objects.create_user(username="seller", password="pass12345")
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(user)
    manor.silver = 100000
    manor.silver_capacity = 200000  # 设置足够大的银库容量
    manor.save()

    # 添加可交易物品到仓库
    InventoryItem.objects.create(
        manor=manor, template=tradeable_item_template, quantity=100, storage_location="warehouse"
    )
    return manor


@pytest.fixture
def buyer_manor(django_user_model):
    """创建买家庄园，拥有足够银两"""
    user = django_user_model.objects.create_user(username="buyer", password="pass12345")
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(user)
    manor.silver = 500000
    manor.silver_capacity = 1000000  # 设置足够大的银库容量
    manor.save()
    return manor


@pytest.mark.django_db
class TestMarketListing:
    """交易行挂单测试"""

    def test_create_listing_success(self, seller_manor, tradeable_item_template):
        """测试成功创建挂单"""
        initial_silver = seller_manor.silver
        initial_quantity = InventoryItem.objects.get(
            manor=seller_manor, template=tradeable_item_template, storage_location="warehouse"
        ).quantity

        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,  # 2小时
        )

        assert listing is not None
        assert listing.quantity == 10
        assert listing.unit_price == 2000
        assert listing.total_price == 20000
        assert listing.status == MarketListing.Status.ACTIVE

        # 验证手续费已扣除
        seller_manor.refresh_from_db()
        assert seller_manor.silver == initial_silver - market_service.LISTING_FEES[7200]

        # 验证物品已扣除
        inventory = InventoryItem.objects.filter(
            manor=seller_manor, template=tradeable_item_template, storage_location="warehouse"
        ).first()
        assert inventory.quantity == initial_quantity - 10

    def test_create_listing_untradeable_item(self, seller_manor, untradeable_item_template):
        """测试上架不可交易物品"""
        # 添加不可交易物品
        InventoryItem.objects.create(
            manor=seller_manor, template=untradeable_item_template, quantity=10, storage_location="warehouse"
        )

        with pytest.raises(ValueError, match="不可交易"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_untradeable_item",
                quantity=5,
                unit_price=1000,
                duration=7200,
            )

    def test_create_listing_insufficient_quantity(self, seller_manor):
        """测试物品数量不足"""
        with pytest.raises(ValueError, match="数量不足"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=1000,  # 超过库存
                unit_price=2000,
                duration=7200,
            )

    def test_create_listing_insufficient_silver(self, seller_manor):
        """测试银两不足支付手续费"""
        seller_manor.silver = 100  # 不够手续费
        seller_manor.save()

        with pytest.raises(ValueError, match="资源不足"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=10,
                unit_price=2000,
                duration=7200,
            )

    def test_create_listing_price_too_low(self, seller_manor, tradeable_item_template):
        """测试定价过低"""
        # 物品基础价格1000，最低定价不能低于1000
        with pytest.raises(ValueError, match="不能低于"):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=10,
                unit_price=500,  # 低于最低价格
                duration=7200,
            )


@pytest.mark.django_db
class TestMarketPurchase:
    """交易行购买测试"""

    def test_purchase_listing_success(self, seller_manor, buyer_manor, tradeable_item_template):
        """测试成功购买挂单"""
        # 先创建挂单
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        seller_initial_silver = Manor.objects.get(pk=seller_manor.pk).silver
        buyer_initial_silver = buyer_manor.silver

        # 购买
        transaction = market_service.purchase_listing(buyer_manor, listing.id)

        assert transaction is not None
        assert transaction.total_price == 20000

        # 验证税费计算（10%）
        assert transaction.tax_amount == 2000
        assert transaction.seller_received == 18000

        # 验证买家银两已扣除
        buyer_manor.refresh_from_db()
        assert buyer_manor.silver == buyer_initial_silver - 20000

        # 验证卖家银两已增加（扣税后）
        seller_manor.refresh_from_db()
        assert seller_manor.silver == seller_initial_silver + 18000

        # 验证买家获得物品
        buyer_inventory = InventoryItem.objects.filter(
            manor=buyer_manor, template=tradeable_item_template, storage_location="warehouse"
        ).first()
        assert buyer_inventory is not None
        assert buyer_inventory.quantity == 10

        # 验证挂单状态已更新
        listing.refresh_from_db()
        assert listing.status == MarketListing.Status.SOLD

    def test_purchase_own_listing(self, seller_manor):
        """测试购买自己的挂单"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        with pytest.raises(ValueError, match="不能购买自己"):
            market_service.purchase_listing(seller_manor, listing.id)

    def test_purchase_insufficient_silver(self, seller_manor, buyer_manor):
        """测试银两不足购买"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=100000,  # 高价
            duration=7200,
        )

        buyer_manor.silver = 1000  # 不够
        buyer_manor.save()

        with pytest.raises(ValueError, match="资源不足"):
            market_service.purchase_listing(buyer_manor, listing.id)

    def test_purchase_expired_listing(self, seller_manor, buyer_manor):
        """测试购买过期挂单"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        # 手动设置为过期
        listing.expires_at = timezone.now() - timedelta(hours=1)
        listing.save()

        with pytest.raises(ValueError, match="已过期"):
            market_service.purchase_listing(buyer_manor, listing.id)

    def test_purchase_listing_succeeds_when_message_send_fails(
        self, seller_manor, buyer_manor, tradeable_item_template, monkeypatch
    ):
        """测试交易成功后消息失败不会导致购买接口报错"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        def _raise_message_error(**_kwargs):
            raise RuntimeError("message backend unavailable")

        monkeypatch.setattr(market_service, "create_message", _raise_message_error)

        transaction = market_service.purchase_listing(buyer_manor, listing.id)

        listing.refresh_from_db()
        assert listing.status == MarketListing.Status.SOLD

        buyer_inventory = InventoryItem.objects.filter(
            manor=buyer_manor, template=tradeable_item_template, storage_location="warehouse"
        ).first()
        assert buyer_inventory is not None
        assert buyer_inventory.quantity == 10

        tx = MarketTransaction.objects.get(pk=transaction.pk)
        assert tx.buyer_mail_sent is False
        assert tx.seller_mail_sent is False


@pytest.mark.django_db
class TestMarketCancel:
    """交易行取消挂单测试"""

    def test_cancel_listing_success(self, seller_manor, tradeable_item_template):
        """测试成功取消挂单"""
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

        # 取消挂单
        result = market_service.cancel_listing(seller_manor, listing.id)

        assert result["quantity"] == 10

        # 验证物品已退回
        inventory = InventoryItem.objects.get(
            manor=seller_manor, template=tradeable_item_template, storage_location="warehouse"
        )
        assert inventory.quantity == initial_quantity  # 物品已退回

        # 验证挂单状态
        listing.refresh_from_db()
        assert listing.status == MarketListing.Status.CANCELLED

    def test_cancel_others_listing(self, seller_manor, buyer_manor):
        """测试取消他人挂单"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )

        with pytest.raises(ValueError, match="无权取消"):
            market_service.cancel_listing(buyer_manor, listing.id)

    def test_cancel_listing_restores_inventory_when_create_races(
        self, seller_manor, tradeable_item_template, monkeypatch
    ):
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )
        InventoryItem.objects.filter(
            manor=seller_manor,
            template=tradeable_item_template,
            storage_location="warehouse",
        ).delete()

        original_create = InventoryItem.objects.create

        def _race_create(**kwargs):
            original_create(**{**kwargs, "quantity": 0})
            raise IntegrityError("duplicate key value violates unique constraint")

        monkeypatch.setattr(InventoryItem.objects, "create", _race_create)

        result = market_service.cancel_listing(seller_manor, listing.id)

        assert result["quantity"] == 10
        inventory = InventoryItem.objects.get(
            manor=seller_manor,
            template=tradeable_item_template,
            storage_location="warehouse",
        )
        assert inventory.quantity == 10


@pytest.mark.django_db
class TestMarketExpire:
    """交易行过期处理测试"""

    def test_expire_listings(self, seller_manor, tradeable_item_template):
        """测试过期挂单处理 - 验证挂单被删除并通过邮件退回物品"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )
        listing_id = listing.id

        # 手动设置为过期
        listing.expires_at = timezone.now() - timedelta(hours=1)
        listing.save()

        # 执行过期处理
        count = market_service.expire_listings()

        assert count == 1

        # 验证挂单记录已删除
        assert not MarketListing.objects.filter(id=listing_id).exists()

        # 验证卖家收到了退回物品的邮件
        from gameplay.models import Message

        message = Message.objects.filter(manor=seller_manor, kind="system", title__contains="交易过期").first()
        assert message is not None
        assert message.attachments.get("items", {}).get("test_tradeable_item") == 10

    def test_expire_listings_still_completes_when_notify_fails(self, seller_manor, monkeypatch):
        """测试过期处理过程中推送失败不会回滚主流程"""
        listing = market_service.create_listing(
            manor=seller_manor,
            item_key="test_tradeable_item",
            quantity=10,
            unit_price=2000,
            duration=7200,
        )
        listing_id = listing.id

        listing.expires_at = timezone.now() - timedelta(hours=1)
        listing.save()

        def _raise_notify_error(*_args, **_kwargs):
            raise RuntimeError("ws unavailable")

        monkeypatch.setattr(market_service, "notify_user", _raise_notify_error)

        count = market_service.expire_listings()
        assert count == 1
        assert not MarketListing.objects.filter(id=listing_id).exists()


@pytest.mark.django_db
class TestMarketQueries:
    """交易行查询测试"""

    def test_get_active_listings(self, seller_manor):
        """测试获取在售挂单"""
        # 创建多个挂单
        for i in range(3):
            market_service.create_listing(
                manor=seller_manor,
                item_key="test_tradeable_item",
                quantity=10,
                unit_price=2000 + i * 100,
                duration=7200,
            )

        listings = market_service.get_active_listings()
        assert listings.count() == 3

    def test_get_my_listings(self, seller_manor):
        """测试获取我的挂单"""
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
        """测试获取可交易物品"""
        # 添加不可交易物品
        InventoryItem.objects.create(
            manor=seller_manor, template=untradeable_item_template, quantity=10, storage_location="warehouse"
        )

        tradeable = market_service.get_tradeable_inventory(seller_manor)
        assert tradeable.count() == 1
        assert tradeable.first().template == tradeable_item_template
