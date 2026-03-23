from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from django_redis.exceptions import ConnectionInterrupted

from tests.helpers.auction import AuctionSlotBidSpec, create_round_and_slot, create_slot_with_bids
from tests.helpers.auction import ensure_auction_item_template as _create_auction_item_template
from trade.models import AuctionRound, AuctionSlot
from trade.services import auction_service
from trade.services.auction_config import AuctionItemConfig, AuctionSettings


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

    monkeypatch.setattr(auction_service, "_settle_slot", lambda slot: (_ for _ in ()).throw(DatabaseError("boom")))

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
        round_id=auction_round.id, settle_slot_func=lambda _slot: (_ for _ in ()).throw(DatabaseError("boom"))
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
def test_rounds_module_settle_auction_round_runtime_error_bubbles_up():
    from trade.services.auction.rounds import settle_auction_round as settle_round_impl

    item_template = _create_auction_item_template("auction_rounds_runtime_error")
    auction_round = AuctionRound.objects.create(
        round_number=10013,
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

    with pytest.raises(RuntimeError, match="boom"):
        settle_round_impl(
            round_id=auction_round.id, settle_slot_func=lambda _slot: (_ for _ in ()).throw(RuntimeError("boom"))
        )

    auction_round.refresh_from_db()
    slot.refresh_from_db()
    assert auction_round.status == AuctionRound.Status.SETTLING
    assert auction_round.settled_at is None
    assert slot.status == AuctionSlot.Status.ACTIVE


@pytest.mark.django_db
def test_rounds_module_settle_auction_round_invalid_settle_result_bubbles_contract_error():
    from trade.services.auction.rounds import settle_auction_round as settle_round_impl

    item_template = _create_auction_item_template("auction_rounds_invalid_settle_result")
    auction_round = AuctionRound.objects.create(
        round_number=10014,
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

    with pytest.raises(AssertionError, match="invalid settle slot result"):
        settle_round_impl(round_id=auction_round.id, settle_slot_func=lambda _slot: None)

    auction_round.refresh_from_db()
    slot.refresh_from_db()
    assert auction_round.status == AuctionRound.Status.SETTLING
    assert auction_round.settled_at is None
    assert slot.status == AuctionSlot.Status.ACTIVE


@pytest.mark.django_db
def test_rounds_module_recovery_programming_error_bubbles_up(monkeypatch, django_user_model):
    from trade.services.auction import rounds as auction_rounds

    setup = create_slot_with_bids(
        django_user_model=django_user_model,
        bid_specs=[AuctionSlotBidSpec(username="auction_recovery_bug", amount=10)],
        item_key="auction_rounds_recovery_programming_error",
        round_number=10015,
        start_at=timezone.now() - timedelta(days=2),
        end_at=timezone.now() - timedelta(minutes=1),
    )

    monkeypatch.setattr(
        auction_rounds,
        "_refund_losing_bids",
        lambda _bids: (_ for _ in ()).throw(AssertionError("refund contract bug")),
    )

    with pytest.raises(AssertionError, match="refund contract bug"):
        auction_rounds.settle_auction_round(
            round_id=setup.auction_round.id,
            settle_slot_func=lambda _slot: (_ for _ in ()).throw(DatabaseError("boom")),
        )

    setup.auction_round.refresh_from_db()
    setup.slot.refresh_from_db()
    assert setup.auction_round.status == AuctionRound.Status.SETTLING
    assert setup.auction_round.settled_at is None
    assert setup.slot.status == AuctionSlot.Status.ACTIVE


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
