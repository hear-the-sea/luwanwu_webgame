from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from django_redis.exceptions import ConnectionInterrupted

from core.exceptions import MessageError
from gameplay.models import InventoryItem, Message
from gameplay.services.manor.core import ensure_manor
from gameplay.services.utils.messages import claim_message_attachments
from tests.helpers.auction import AuctionSlotBidSpec, create_round_and_slot, create_slot_with_bids
from tests.helpers.auction import ensure_auction_item_template as _create_auction_item_template
from tests.helpers.auction import ensure_gold_bar_template as _ensure_gold_bar_template
from trade.models import AuctionBid, AuctionRound, AuctionSlot, FrozenGoldBar
from trade.services import auction_service
from trade.services.auction_config import AuctionItemConfig, AuctionSettings
from trade.services.bank_service import (
    GOLD_BAR_BASE_PRICE,
    GOLD_BAR_MAX_PRICE,
    GOLD_BAR_MIN_PRICE,
    calculate_next_rate,
    calculate_progressive_factor,
)


@pytest.mark.django_db
def test_create_auction_round_skips_when_settling_round_exists(monkeypatch):
    item_key = "auction_round_create_guard"
    _create_auction_item_template(item_key)

    AuctionRound.objects.create(
        round_number=10001,
        status=AuctionRound.Status.SETTLING,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(days=1),
    )

    monkeypatch.setattr(
        auction_service,
        "get_auction_settings",
        lambda: AuctionSettings(cycle_days=3, min_increment_ratio=0.1, default_min_increment=1),
    )
    monkeypatch.setattr(
        auction_service,
        "get_enabled_auction_items",
        lambda: [
            AuctionItemConfig(
                item_key=item_key,
                slots=1,
                quantity_per_slot=1,
                starting_price=10,
                min_increment=1,
                enabled=True,
            )
        ],
    )

    created = auction_service.create_auction_round()

    assert created is None
    assert AuctionRound.objects.count() == 1


@pytest.mark.django_db
def test_rounds_module_create_auction_round_can_create_slots(monkeypatch):
    from trade.services.auction.rounds import create_auction_round as create_round_impl

    item_key = "auction_rounds_impl_create"
    _create_auction_item_template(item_key)

    monkeypatch.setattr(
        "trade.services.auction.rounds.get_auction_settings",
        lambda: AuctionSettings(cycle_days=3, min_increment_ratio=0.1, default_min_increment=1),
    )
    monkeypatch.setattr(
        "trade.services.auction.rounds.get_enabled_auction_items",
        lambda: [
            AuctionItemConfig(
                item_key=item_key,
                slots=2,
                quantity_per_slot=1,
                starting_price=10,
                min_increment=1,
                enabled=True,
            )
        ],
    )

    created = create_round_impl()

    assert created is not None
    assert created.slots.count() == 2


@pytest.mark.django_db
def test_rounds_module_create_auction_round_skips_when_cache_add_fails(monkeypatch):
    from trade.services.auction.rounds import create_auction_round as create_round_impl

    item_key = "auction_rounds_cache_add_fail_create"
    _create_auction_item_template(item_key)

    monkeypatch.setattr(
        "trade.services.auction.rounds.cache.add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )
    monkeypatch.setattr(
        "trade.services.auction.rounds.get_auction_settings",
        lambda: AuctionSettings(cycle_days=3, min_increment_ratio=0.1, default_min_increment=1),
    )
    monkeypatch.setattr(
        "trade.services.auction.rounds.get_enabled_auction_items",
        lambda: [
            AuctionItemConfig(
                item_key=item_key,
                slots=1,
                quantity_per_slot=1,
                starting_price=10,
                min_increment=1,
                enabled=True,
            )
        ],
    )

    created = create_round_impl()

    assert created is None
    assert AuctionRound.objects.count() == 0


@pytest.mark.django_db
def test_auction_round_db_constraint_allows_only_one_active_round():
    now = timezone.now()
    AuctionRound.objects.create(
        round_number=11001,
        status=AuctionRound.Status.ACTIVE,
        start_at=now - timedelta(days=1),
        end_at=now + timedelta(days=1),
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuctionRound.objects.create(
                round_number=11002,
                status=AuctionRound.Status.ACTIVE,
                start_at=now - timedelta(hours=1),
                end_at=now + timedelta(days=2),
            )

    first = AuctionRound.objects.get(round_number=11001)
    assert first.status_singleton == AuctionRound.Status.ACTIVE


@pytest.mark.django_db
def test_auction_round_db_constraint_allows_only_one_settling_round():
    now = timezone.now()
    AuctionRound.objects.create(
        round_number=12001,
        status=AuctionRound.Status.SETTLING,
        start_at=now - timedelta(days=3),
        end_at=now - timedelta(hours=1),
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuctionRound.objects.create(
                round_number=12002,
                status=AuctionRound.Status.SETTLING,
                start_at=now - timedelta(days=2),
                end_at=now - timedelta(minutes=30),
            )

    first = AuctionRound.objects.get(round_number=12001)
    assert first.status_singleton == AuctionRound.Status.SETTLING


@pytest.mark.django_db
def test_auction_round_completed_status_clears_singleton_value():
    now = timezone.now()
    round_obj = AuctionRound.objects.create(
        round_number=13001,
        status=AuctionRound.Status.ACTIVE,
        start_at=now - timedelta(days=1),
        end_at=now + timedelta(days=1),
    )

    round_obj.status = AuctionRound.Status.COMPLETED
    round_obj.save(update_fields=["status"])
    round_obj.refresh_from_db()

    assert round_obj.status_singleton is None


@pytest.mark.django_db
def test_settle_auction_round_marks_failed_slot_unsold_and_completes_round(monkeypatch):
    auction_round, slot = create_round_and_slot(
        item_key="auction_settle_failure_item",
        round_number=10002,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    monkeypatch.setattr(auction_service, "_settle_slot", lambda slot: (_ for _ in ()).throw(RuntimeError("boom")))

    stats = auction_service.settle_auction_round(round_id=auction_round.id)

    auction_round.refresh_from_db()
    slot.refresh_from_db()
    assert stats["settled"] == 1
    assert stats["unsold"] == 1
    assert stats["recovered_failures"] == 1
    assert auction_round.status == AuctionRound.Status.COMPLETED
    assert auction_round.settled_at is not None
    assert slot.status == AuctionSlot.Status.UNSOLD


@pytest.mark.django_db
def test_rounds_module_settle_auction_round_marks_completed_when_no_slots():
    from trade.services.auction.rounds import settle_auction_round as settle_round_impl

    auction_round = AuctionRound.objects.create(
        round_number=10004,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    stats = settle_round_impl(round_id=auction_round.id)

    auction_round.refresh_from_db()
    assert stats["settled"] == 1
    assert auction_round.status == AuctionRound.Status.COMPLETED
    assert auction_round.settled_at is not None


@pytest.mark.django_db
def test_settle_auction_round_without_round_id_resumes_settling_round():
    auction_round = AuctionRound.objects.create(
        round_number=10011,
        status=AuctionRound.Status.SETTLING,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    stats = auction_service.settle_auction_round()

    auction_round.refresh_from_db()
    assert stats["settled"] == 1
    assert stats["sold"] == 0
    assert stats["unsold"] == 0
    assert auction_round.status == AuctionRound.Status.COMPLETED
    assert auction_round.settled_at is not None


@pytest.mark.django_db
def test_settle_auction_round_without_round_id_resumes_settling_active_slots(monkeypatch):
    auction_round, slot = create_round_and_slot(
        item_key="auction_settling_resume_active_slot",
        round_number=10014,
        round_status=AuctionRound.Status.SETTLING,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    def _settle_unsold(slot_to_settle):
        AuctionSlot.objects.filter(pk=slot_to_settle.pk).update(status=AuctionSlot.Status.UNSOLD)
        return {"sold": False, "price": 0}

    monkeypatch.setattr(auction_service, "_settle_slot", _settle_unsold)

    stats = auction_service.settle_auction_round()

    auction_round.refresh_from_db()
    slot.refresh_from_db()
    assert stats["settled"] == 1
    assert stats["unsold"] == 1
    assert auction_round.status == AuctionRound.Status.COMPLETED
    assert slot.status == AuctionSlot.Status.UNSOLD


@pytest.mark.django_db
def test_rounds_module_settle_slot_skips_non_active_slot():
    from trade.services.auction.rounds import _settle_slot

    item_tpl = _create_auction_item_template("auction_settle_skip_non_active_item")
    auction_round = AuctionRound.objects.create(
        round_number=10012,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.SOLD,
        config_key=item_tpl.key,
        slot_index=0,
    )

    with TestCase.captureOnCommitCallbacks(execute=True):
        result = _settle_slot(slot)
    slot.refresh_from_db()

    assert result.get("skipped") is True
    assert slot.status == AuctionSlot.Status.SOLD


@pytest.mark.django_db
def test_rounds_module_settle_auction_round_keeps_settling_when_active_slots_remain():
    from trade.services.auction.rounds import settle_auction_round as settle_round_impl

    item_template = _create_auction_item_template("auction_rounds_keep_settling_when_active")
    auction_round = AuctionRound.objects.create(
        round_number=10013,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_template,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_template.key,
        slot_index=0,
    )

    stats = settle_round_impl(round_id=auction_round.id, settle_slot_func=lambda _slot: {"skipped": True})

    auction_round.refresh_from_db()
    assert stats["settled"] == 0
    assert auction_round.status == AuctionRound.Status.SETTLING
    assert auction_round.settled_at is None


@pytest.mark.django_db
def test_rounds_module_settle_auction_round_marks_failed_slot_unsold(monkeypatch):
    from trade.services.auction.rounds import settle_auction_round as settle_round_impl

    item_template = _create_auction_item_template("auction_rounds_impl_failure")
    auction_round = AuctionRound.objects.create(
        round_number=10005,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_template,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_template.key,
        slot_index=0,
    )

    stats = settle_round_impl(
        round_id=auction_round.id, settle_slot_func=lambda _slot: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    auction_round.refresh_from_db()
    slot.refresh_from_db()
    assert stats["settled"] == 1
    assert stats["unsold"] == 1
    assert stats["recovered_failures"] == 1
    assert auction_round.status == AuctionRound.Status.COMPLETED
    assert auction_round.settled_at is not None
    assert slot.status == AuctionSlot.Status.UNSOLD


@pytest.mark.django_db
def test_rounds_module_settle_slot_marks_unsold_when_no_bids():
    from trade.services.auction.rounds import _settle_slot

    item_tpl = _create_auction_item_template("auction_settle_unsold_item")
    auction_round = AuctionRound.objects.create(
        round_number=10006,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )

    with TestCase.captureOnCommitCallbacks(execute=True):
        result = _settle_slot(slot)
    slot.refresh_from_db()

    assert result["sold"] is False
    assert slot.status == AuctionSlot.Status.UNSOLD


@pytest.mark.django_db
def test_rounds_module_settle_slot_invalid_winner_count_refunds_all_bids(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_settle_invalid_winner_count", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_invalid_winner_item")
    auction_round = AuctionRound.objects.create(
        round_number=10009,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=0,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot, manor=manor, amount=20, status=AuctionBid.Status.ACTIVE, frozen_gold_bars=20
    )
    frozen = FrozenGoldBar.objects.create(
        manor=manor,
        amount=20,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    monkeypatch.setattr("trade.services.auction.rounds.create_message", lambda *a, **k: None)
    monkeypatch.setattr("trade.services.auction.rounds.notify_user", lambda *a, **k: True)

    with TestCase.captureOnCommitCallbacks(execute=True):
        result = _settle_slot(slot)

    bid.refresh_from_db()
    frozen.refresh_from_db()
    slot.refresh_from_db()

    assert result["sold"] is False
    assert result["price"] == 0
    assert slot.status == AuctionSlot.Status.UNSOLD
    assert bid.status == AuctionBid.Status.REFUNDED
    assert frozen.is_frozen is False


@pytest.mark.django_db
def test_rounds_module_settle_slot_partial_refund_flow(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_rounds_settle_user", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_partial_refund_item")
    auction_round = AuctionRound.objects.create(
        round_number=10005,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot, manor=manor, amount=20, status=AuctionBid.Status.ACTIVE, frozen_gold_bars=20
    )

    FrozenGoldBar.objects.create(
        manor=manor,
        amount=20,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    # Avoid inventory manipulation during unit test; we only need to cover control-flow.
    monkeypatch.setattr(
        "trade.services.auction.gold_bars.consume_inventory_item_for_manor_locked", lambda *a, **k: None
    )
    monkeypatch.setattr("trade.services.auction.rounds.create_message", lambda *a, **k: None)
    monkeypatch.setattr("trade.services.auction.rounds.notify_user", lambda *a, **k: True)

    with TestCase.captureOnCommitCallbacks(execute=True):
        result = _settle_slot(slot)

    bid.refresh_from_db()
    slot.refresh_from_db()

    assert result["sold"] is True
    assert slot.status == AuctionSlot.Status.SOLD
    assert bid.status == AuctionBid.Status.WON


@pytest.mark.django_db
def test_rounds_module_settle_slot_raises_when_winner_missing_frozen_record(django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_settle_missing_frozen", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_missing_frozen_item")
    auction_round = AuctionRound.objects.create(
        round_number=10017,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot,
        manor=manor,
        amount=20,
        status=AuctionBid.Status.ACTIVE,
        frozen_gold_bars=20,
    )

    with pytest.raises(RuntimeError, match="missing frozen record"):
        _settle_slot(slot)

    # 事务回滚：拍卖位与出价状态保持未结算，避免“未扣费已发货”。
    slot.refresh_from_db()
    bid.refresh_from_db()
    assert slot.status == AuctionSlot.Status.ACTIVE
    assert bid.status == AuctionBid.Status.ACTIVE


@pytest.mark.django_db
def test_rounds_module_settle_slot_does_not_emit_notifications_before_commit(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user_one = django_user_model.objects.create_user(username="auction_rounds_notify_a", password="pass123")
    user_two = django_user_model.objects.create_user(username="auction_rounds_notify_b", password="pass123")
    manor_one = ensure_manor(user_one)
    manor_two = ensure_manor(user_two)

    item_tpl = _create_auction_item_template("auction_settle_notify_after_commit_item")
    auction_round = AuctionRound.objects.create(
        round_number=10018,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=2,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    first_bid = AuctionBid.objects.create(
        slot=slot,
        manor=manor_one,
        amount=20,
        status=AuctionBid.Status.ACTIVE,
        frozen_gold_bars=20,
    )
    second_bid = AuctionBid.objects.create(
        slot=slot,
        manor=manor_two,
        amount=18,
        status=AuctionBid.Status.ACTIVE,
        frozen_gold_bars=18,
    )

    consume_calls = {"count": 0}
    emitted_messages: list[tuple] = []
    emitted_notifications: list[tuple] = []

    def _consume_or_fail(*_args, **_kwargs):
        consume_calls["count"] += 1
        if consume_calls["count"] == 2:
            raise RuntimeError("boom on second winner")

    monkeypatch.setattr("trade.services.auction.rounds._consume_winning_bid_frozen_gold_bars", _consume_or_fail)
    monkeypatch.setattr(
        "trade.services.auction.rounds.create_message", lambda *args, **kwargs: emitted_messages.append((args, kwargs))
    )
    monkeypatch.setattr(
        "trade.services.auction.rounds.notify_user",
        lambda *args, **kwargs: emitted_notifications.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="boom on second winner"):
        _settle_slot(slot)

    slot.refresh_from_db()
    first_bid.refresh_from_db()
    second_bid.refresh_from_db()

    assert slot.status == AuctionSlot.Status.ACTIVE
    assert first_bid.status == AuctionBid.Status.ACTIVE
    assert second_bid.status == AuctionBid.Status.ACTIVE
    assert emitted_messages == []
    assert emitted_notifications == []


@pytest.mark.django_db
def test_rounds_module_settle_slot_delivers_item_via_message_attachment(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    slot_with_bids = create_slot_with_bids(
        django_user_model=django_user_model,
        bid_specs=[AuctionSlotBidSpec(username="auction_rounds_attachment_flow", amount=20)],
        item_key="auction_settle_attachment_item",
        round_number=10014,
        starting_price=10,
        min_increment=1,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = slot_with_bids.slot
    bid = slot_with_bids.bids[0]
    manor = slot_with_bids.manors_by_username["auction_rounds_attachment_flow"]
    item_tpl = slot.item_template
    gold_tpl = _ensure_gold_bar_template()
    InventoryItem.objects.create(
        manor=manor,
        template=gold_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        quantity=30,
    )
    monkeypatch.setattr("trade.services.auction.rounds.notify_user", lambda *a, **k: True)

    with TestCase.captureOnCommitCallbacks(execute=True):
        result = _settle_slot(slot)

    bid.refresh_from_db()
    slot.refresh_from_db()

    assert result["sold"] is True
    assert slot.status == AuctionSlot.Status.SOLD
    assert bid.status == AuctionBid.Status.WON
    assert not InventoryItem.objects.filter(
        manor=manor,
        template=item_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()

    message = Message.objects.filter(manor=manor, title__contains="拍卖行").order_by("-id").first()
    assert message is not None
    assert message.is_claimed is False
    assert message.attachments.get("items", {}).get(item_tpl.key) == 1

    claim_message_attachments(message)
    item_after_claim = InventoryItem.objects.get(
        manor=manor,
        template=item_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert item_after_claim.quantity == 1


@pytest.mark.django_db
def test_rounds_module_settle_slot_falls_back_to_direct_grant_when_message_create_fails(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_rounds_message_fallback", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_direct_grant_item")
    gold_tpl = _ensure_gold_bar_template()
    InventoryItem.objects.create(
        manor=manor,
        template=gold_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        quantity=30,
    )
    auction_round = AuctionRound.objects.create(
        round_number=10015,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot,
        manor=manor,
        amount=20,
        status=AuctionBid.Status.ACTIVE,
        frozen_gold_bars=20,
    )
    FrozenGoldBar.objects.create(
        manor=manor,
        amount=20,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    monkeypatch.setattr(
        "trade.services.auction.rounds.create_message",
        lambda *a, **k: (_ for _ in ()).throw(MessageError("message unavailable")),
    )
    monkeypatch.setattr("trade.services.auction.rounds.notify_user", lambda *a, **k: True)

    with TestCase.captureOnCommitCallbacks(execute=True):
        result = _settle_slot(slot)

    bid.refresh_from_db()
    slot.refresh_from_db()

    assert result["sold"] is True
    assert slot.status == AuctionSlot.Status.SOLD
    assert bid.status == AuctionBid.Status.WON
    assert not Message.objects.filter(manor=manor, title__contains="拍卖行").exists()

    granted_item = InventoryItem.objects.get(
        manor=manor,
        template=item_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert granted_item.quantity == 1


@pytest.mark.django_db
def test_rounds_module_settle_slot_runtime_marker_message_error_bubbles_up(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_rounds_message_runtime", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_direct_runtime_item")
    gold_tpl = _ensure_gold_bar_template()
    InventoryItem.objects.create(
        manor=manor,
        template=gold_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        quantity=30,
    )
    auction_round = AuctionRound.objects.create(
        round_number=10016,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot,
        manor=manor,
        amount=20,
        status=AuctionBid.Status.ACTIVE,
        frozen_gold_bars=20,
    )
    FrozenGoldBar.objects.create(
        manor=manor,
        amount=20,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    monkeypatch.setattr(
        "trade.services.auction.rounds.create_message",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )
    monkeypatch.setattr("trade.services.auction.rounds.notify_user", lambda *a, **k: True)

    with pytest.raises(RuntimeError, match="message backend down"):
        with TestCase.captureOnCommitCallbacks(execute=True):
            _settle_slot(slot)

    assert not Message.objects.filter(manor=manor, title__contains="拍卖行").exists()
    assert not InventoryItem.objects.filter(
        manor=manor,
        template=item_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()


@pytest.mark.django_db
def test_rounds_module_settle_slot_ignores_notify_failure(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_rounds_notify_fail", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_notify_fail_item")
    auction_round = AuctionRound.objects.create(
        round_number=10008,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot, manor=manor, amount=20, status=AuctionBid.Status.ACTIVE, frozen_gold_bars=20
    )

    FrozenGoldBar.objects.create(
        manor=manor,
        amount=20,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    monkeypatch.setattr(
        "trade.services.auction.gold_bars.consume_inventory_item_for_manor_locked", lambda *a, **k: None
    )
    monkeypatch.setattr("trade.services.auction.rounds.create_message", lambda *a, **k: None)
    monkeypatch.setattr(
        "trade.services.auction.rounds.notify_user",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("ws unavailable")),
    )

    result = _settle_slot(slot)

    bid.refresh_from_db()
    slot.refresh_from_db()
    assert result["sold"] is True
    assert slot.status == AuctionSlot.Status.SOLD
    assert bid.status == AuctionBid.Status.WON


@pytest.mark.django_db
def test_rounds_module_settle_slot_runtime_marker_notify_error_bubbles_up(monkeypatch, django_user_model):
    from trade.services.auction.rounds import _settle_slot

    user = django_user_model.objects.create_user(username="auction_rounds_notify_runtime", password="pass123")
    manor = ensure_manor(user)

    item_tpl = _create_auction_item_template("auction_settle_notify_runtime_item")
    auction_round = AuctionRound.objects.create(
        round_number=10017,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=item_tpl,
        quantity=1,
        starting_price=10,
        current_price=10,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=item_tpl.key,
        slot_index=0,
    )
    bid = AuctionBid.objects.create(
        slot=slot, manor=manor, amount=20, status=AuctionBid.Status.ACTIVE, frozen_gold_bars=20
    )
    FrozenGoldBar.objects.create(
        manor=manor,
        amount=20,
        reason=FrozenGoldBar.Reason.AUCTION_BID,
        auction_bid=bid,
        is_frozen=True,
    )

    monkeypatch.setattr(
        "trade.services.auction.gold_bars.consume_inventory_item_for_manor_locked", lambda *a, **k: None
    )
    monkeypatch.setattr("trade.services.auction.rounds.create_message", lambda *a, **k: None)
    monkeypatch.setattr(
        "trade.services.auction.rounds.notify_user",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        with TestCase.captureOnCommitCallbacks(execute=True):
            _settle_slot(slot)


@pytest.mark.django_db
def test_settle_auction_round_can_resume_from_settling_status():
    auction_round = AuctionRound.objects.create(
        round_number=10003,
        status=AuctionRound.Status.SETTLING,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    stats = auction_service.settle_auction_round(round_id=auction_round.id)

    auction_round.refresh_from_db()
    assert stats["settled"] == 1
    assert auction_round.status == AuctionRound.Status.COMPLETED
    assert auction_round.settled_at is not None


@pytest.mark.django_db
def test_rounds_module_settle_auction_round_skips_when_cache_add_fails(monkeypatch):
    from trade.services.auction.rounds import settle_auction_round as settle_round_impl

    auction_round = AuctionRound.objects.create(
        round_number=10010,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    monkeypatch.setattr(
        "trade.services.auction.rounds.cache.add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )
    stats = settle_round_impl(round_id=auction_round.id)

    auction_round.refresh_from_db()
    assert stats["settled"] == 0
    assert auction_round.status == AuctionRound.Status.ACTIVE


@pytest.mark.django_db
def test_rounds_module_create_auction_round_runtime_marker_cache_add_bubbles_up(monkeypatch):
    from trade.services.auction.rounds import create_auction_round as create_round_impl

    monkeypatch.setattr(
        "trade.services.auction.rounds.cache.add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    with pytest.raises(RuntimeError, match="cache down"):
        create_round_impl()


@pytest.mark.django_db
def test_calculate_next_rate_uses_next_exchange_step(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="bank_next_rate", password="pass12345")
    manor = ensure_manor(user)

    monkeypatch.setattr("trade.services.bank_service.calculate_supply_factor", lambda: 1.0)
    monkeypatch.setattr("trade.services.bank_service.get_today_exchange_count", lambda _manor: 2)

    rate = calculate_next_rate(manor)

    expected = int(GOLD_BAR_BASE_PRICE * 1.0 * calculate_progressive_factor(3))
    expected = max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, expected))
    assert rate == expected
