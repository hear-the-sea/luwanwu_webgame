from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor import ensure_manor
from trade.models import AuctionBid, AuctionRound, AuctionSlot
from trade.services import auction_service


def _ensure_gold_bar_template() -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key=auction_service.GOLD_BAR_ITEM_KEY,
        defaults={
            "name": "金条",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    return template


def _set_gold_bars(manor, quantity: int) -> None:
    template = _ensure_gold_bar_template()
    InventoryItem.objects.update_or_create(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": int(quantity)},
    )


def _create_active_round_and_slot(*, item_key: str, quantity: int = 1) -> AuctionSlot:
    item_template, _ = ItemTemplate.objects.get_or_create(
        key=item_key,
        defaults={
            "name": "拍卖测试物品",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    auction_round = AuctionRound.objects.create(
        round_number=20001,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(hours=1),
        end_at=timezone.now() + timedelta(hours=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_template,
        quantity=int(quantity),
        starting_price=2,
        current_price=2,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_template.key,
        slot_index=0,
    )
    return slot


@pytest.mark.django_db
def test_validate_bid_amount_rejects_below_starting_price(django_user_model):
    user = django_user_model.objects.create_user(username="auction_validate", password="pass12345")
    _ = ensure_manor(user)

    slot = _create_active_round_and_slot(item_key="auction_validate_item")
    slot.bid_count = 0

    with pytest.raises(ValueError, match="起拍价"):
        auction_service.validate_bid_amount(slot, 1)


@pytest.mark.django_db
def test_place_bid_freezes_and_unfreezes_gold_bars(monkeypatch, django_user_model):
    monkeypatch.setattr(auction_service, "_notify_outbid_vickrey", lambda *args, **kwargs: None)

    user = django_user_model.objects.create_user(username="auction_freeze", password="pass12345")
    manor = ensure_manor(user)
    _set_gold_bars(manor, 10)

    slot = _create_active_round_and_slot(item_key="auction_freeze_item")

    bid, is_first = auction_service.place_bid(manor, slot.id, 5)
    assert is_first is True

    bid.refresh_from_db()
    frozen = bid.frozen_record
    assert frozen.is_frozen is True
    assert frozen.amount == 5
    assert bid.frozen_gold_bars == 5
    assert auction_service.get_available_gold_bars(manor) == 5

    auction_service.unfreeze_gold_bars(frozen)
    frozen.refresh_from_db()
    bid.refresh_from_db()
    assert frozen.is_frozen is False
    assert bid.status == AuctionBid.Status.REFUNDED
    assert auction_service.get_available_gold_bars(manor) == 10


@pytest.mark.django_db
def test_place_bid_kicks_out_previous_winner_and_refunds(monkeypatch, django_user_model):
    monkeypatch.setattr(auction_service, "_notify_outbid_vickrey", lambda *args, **kwargs: None)

    user1 = django_user_model.objects.create_user(username="auction_kick1", password="pass12345")
    user2 = django_user_model.objects.create_user(username="auction_kick2", password="pass12345")
    manor1 = ensure_manor(user1)
    manor2 = ensure_manor(user2)
    _set_gold_bars(manor1, 10)
    _set_gold_bars(manor2, 10)

    slot = _create_active_round_and_slot(item_key="auction_kick_item", quantity=1)

    bid1, _ = auction_service.place_bid(manor1, slot.id, 5)
    bid2, _ = auction_service.place_bid(manor2, slot.id, 6)

    bid1.refresh_from_db()
    bid2.refresh_from_db()
    slot.refresh_from_db()

    assert bid2.status == AuctionBid.Status.ACTIVE
    assert bid2.frozen_record.is_frozen is True

    # bid1 should be refunded after being kicked out.
    assert bid1.status == AuctionBid.Status.REFUNDED
    assert bid1.frozen_record.is_frozen is False
    assert auction_service.get_available_gold_bars(manor1) == 10

    assert slot.highest_bidder_id == manor2.id
    assert slot.current_price == 6

    # Winner consumption should decrease actual inventory.
    auction_service.consume_frozen_gold_bars(bid2.frozen_record, manor2)
    bid2.refresh_from_db()
    bid2.frozen_record.refresh_from_db()

    assert bid2.status == AuctionBid.Status.WON
    assert bid2.frozen_record.is_frozen is False
    assert auction_service.get_total_gold_bars(manor2) == 4


@pytest.mark.django_db
def test_place_bid_allows_same_player_to_raise_bid_and_unfreezes_previous(monkeypatch, django_user_model):
    monkeypatch.setattr(auction_service, "_notify_outbid_vickrey", lambda *args, **kwargs: None)

    user = django_user_model.objects.create_user(username="auction_raise", password="pass12345")
    manor = ensure_manor(user)
    _set_gold_bars(manor, 12)

    slot = _create_active_round_and_slot(item_key="auction_raise_item", quantity=2)

    bid1, is_first = auction_service.place_bid(manor, slot.id, 5)
    assert is_first is True
    assert auction_service.get_available_gold_bars(manor) == 7

    bid2, is_first = auction_service.place_bid(manor, slot.id, 7)
    assert is_first is False

    bid1.refresh_from_db()
    bid1.frozen_record.refresh_from_db()
    bid2.refresh_from_db()
    bid2.frozen_record.refresh_from_db()

    # Old bid is replaced by the player's new bid and marked OUTBID.
    # The refund status is tracked on the FrozenGoldBar record.
    assert bid1.status == AuctionBid.Status.OUTBID
    assert bid1.frozen_record.is_frozen is False
    assert bid2.status == AuctionBid.Status.ACTIVE
    assert bid2.frozen_record.is_frozen is True
    assert auction_service.get_available_gold_bars(manor) == 5


@pytest.mark.django_db
def test_place_bid_succeeds_when_outbid_notification_fails(monkeypatch, django_user_model):
    user1 = django_user_model.objects.create_user(username="auction_notify_fail_1", password="pass12345")
    user2 = django_user_model.objects.create_user(username="auction_notify_fail_2", password="pass12345")
    manor1 = ensure_manor(user1)
    manor2 = ensure_manor(user2)
    _set_gold_bars(manor1, 10)
    _set_gold_bars(manor2, 10)

    slot = _create_active_round_and_slot(item_key="auction_notify_fail_item", quantity=1)

    auction_service.place_bid(manor1, slot.id, 5)
    monkeypatch.setattr("trade.services.auction.bidding.create_message", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("msg down")))
    monkeypatch.setattr("trade.services.auction.bidding.notify_user", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ws down")))

    bid2, _ = auction_service.place_bid(manor2, slot.id, 6)
    bid2.refresh_from_db()

    assert bid2.status == AuctionBid.Status.ACTIVE
    assert bid2.frozen_record.is_frozen is True


@pytest.mark.django_db
def test_validate_bid_amount_rejects_non_positive_amount(django_user_model):
    user = django_user_model.objects.create_user(username="auction_validate_non_positive", password="pass12345")
    _ = ensure_manor(user)

    slot = _create_active_round_and_slot(item_key="auction_validate_non_positive_item")
    slot.bid_count = 0

    with pytest.raises(ValueError, match="出价金额必须大于0"):
        auction_service.validate_bid_amount(slot, 0)


@pytest.mark.django_db
def test_place_bid_rejects_invalid_amount_type(django_user_model):
    user = django_user_model.objects.create_user(username="auction_invalid_amount_type", password="pass12345")
    manor = ensure_manor(user)
    _set_gold_bars(manor, 10)
    slot = _create_active_round_and_slot(item_key="auction_invalid_amount_type_item")

    with pytest.raises(ValueError, match="出价金额必须大于0"):
        auction_service.place_bid(manor, slot.id, "invalid")


@pytest.mark.django_db
def test_place_bid_rejects_invalid_winner_count_configuration(django_user_model):
    user = django_user_model.objects.create_user(username="auction_invalid_winner_count", password="pass12345")
    manor = ensure_manor(user)
    _set_gold_bars(manor, 10)
    slot = _create_active_round_and_slot(item_key="auction_invalid_winner_count_item", quantity=1)
    slot.quantity = 0
    slot.save(update_fields=["quantity"])

    with pytest.raises(ValueError, match="拍卖位配置异常"):
        auction_service.place_bid(manor, slot.id, 5)
