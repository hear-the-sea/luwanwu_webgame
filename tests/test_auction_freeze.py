import pytest
from django.db import transaction

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor import ensure_manor
from trade.models import AuctionBid, AuctionRound, AuctionSlot
from trade.services.auction_service import freeze_gold_bars


@pytest.mark.django_db
def test_freeze_gold_bars_respects_available_inventory(django_user_model):
    user = django_user_model.objects.create_user(username="auctioneer", password="pass123")
    manor = ensure_manor(user)

    gold_tpl, _ = ItemTemplate.objects.get_or_create(
        key="gold_bar",
        defaults={
            "name": "金条",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": True,
            "tradeable": False,
        },
    )
    InventoryItem.objects.update_or_create(
        manor=manor,
        template=gold_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": 5},
    )

    auction_item, _ = ItemTemplate.objects.get_or_create(
        key="auction_item_dummy",
        defaults={
            "name": "拍卖测试物品",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    round_obj = AuctionRound.objects.create(
        round_number=999,
        status=AuctionRound.Status.ACTIVE,
        start_at=manor.created_at,
        end_at=manor.created_at,
    )
    slot = AuctionSlot.objects.create(
        round=round_obj,
        item_template=auction_item,
        quantity=1,
        starting_price=1,
        current_price=1,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key="auction_item_dummy",
        slot_index=0,
    )

    bid1 = AuctionBid.objects.create(slot=slot, manor=manor, amount=3, status=AuctionBid.Status.ACTIVE)
    bid2 = AuctionBid.objects.create(slot=slot, manor=manor, amount=3, status=AuctionBid.Status.ACTIVE)

    with transaction.atomic():
        freeze_gold_bars(manor, 3, bid1)
        with pytest.raises(ValueError):
            freeze_gold_bars(manor, 3, bid2)
