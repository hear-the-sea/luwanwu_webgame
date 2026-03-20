from __future__ import annotations

import logging
import time
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

import gameplay.services.missions_impl.execution as mission_execution
from battle.models import TroopTemplate
from gameplay.models import (
    InventoryItem,
    ItemTemplate,
    Message,
    MissionRun,
    MissionTemplate,
    PlayerTroop,
    RaidRun,
    ResourceEvent,
    ResourceType,
    ScoutCooldown,
    ScoutRecord,
)
from gameplay.services.manor.core import ensure_manor
from gameplay.services.missions import launch_mission, refresh_mission_runs
from gameplay.services.raid import refresh_scout_records, request_raid_retreat
from gameplay.services.raid import scout_refresh as scout_refresh_command
from gameplay.services.raid import start_raid, start_scout
from gameplay.services.utils.cache import CacheKeys
from gameplay.services.utils.messages import claim_message_attachments
from gameplay.tasks import complete_mission_task, complete_raid_task
from gameplay.tasks.pvp import complete_scout_return_task, complete_scout_task, process_raid_battle_task
from guests.models import RecruitmentPool
from guests.services.recruitment import recruit_guest, refresh_guest_recruitments, start_guest_recruitment
from guests.services.recruitment_guests import finalize_candidate
from guilds.constants import CONTRIBUTION_RATES, GUILD_CREATION_COST
from guilds.models import GuildAnnouncement, GuildDonationLog, GuildMember, GuildResourceLog
from guilds.services.contribution import donate_resource
from guilds.services.guild import create_guild
from guilds.services.member import apply_to_guild, approve_application
from trade.models import AuctionBid, AuctionRound, AuctionSlot, MarketListing
from trade.services.auction_service import place_bid, settle_auction_round
from trade.services.market_service import create_listing, purchase_listing

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("load_guest_data")]


def _prepare_attack_ready_manors(django_user_model, *, prefix: str):
    attacker_user = django_user_model.objects.create_user(
        username=f"{prefix}_attacker_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    defender_user = django_user_model.objects.create_user(
        username=f"{prefix}_defender_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    for manor in (attacker, defender):
        manor.newbie_protection_until = timezone.now() - timedelta(days=1)
        manor.peace_shield_until = None
        manor.defeat_protection_until = None
        manor.prestige = 100
        manor.grain = 500000
        manor.silver = 500000
        manor.save(
            update_fields=[
                "newbie_protection_until",
                "peace_shield_until",
                "defeat_protection_until",
                "prestige",
                "grain",
                "silver",
            ]
        )

    return attacker, defender


@pytest.mark.django_db(transaction=True)
def test_integration_market_purchase_flow(require_env_services, django_user_model):
    seller_user = django_user_model.objects.create_user(
        username=f"intg_seller_{uuid.uuid4().hex[:8]}", password="pass123"
    )
    buyer_user = django_user_model.objects.create_user(
        username=f"intg_buyer_{uuid.uuid4().hex[:8]}", password="pass123"
    )
    seller = ensure_manor(seller_user)
    buyer = ensure_manor(buyer_user)

    seller.silver = 100000
    buyer.silver = 200000
    seller.save(update_fields=["silver"])
    buyer.save(update_fields=["silver"])

    item_key = f"intg_market_item_{uuid.uuid4().hex[:8]}"
    template = ItemTemplate.objects.create(
        key=item_key,
        name="集成测试交易物品",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=True,
        price=1000,
    )
    InventoryItem.objects.create(
        manor=seller,
        template=template,
        quantity=5,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    listing = create_listing(seller, item_key, quantity=2, unit_price=3000, duration=7200)
    transaction_record = purchase_listing(buyer, listing.id)

    listing.refresh_from_db()
    buyer_item = InventoryItem.objects.get(
        manor=buyer,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    assert listing.status == MarketListing.Status.SOLD
    assert transaction_record.total_price == 6000
    assert buyer_item.quantity == 2


@pytest.mark.django_db(transaction=True)
def test_integration_auction_bid_and_settlement_flow(require_env_services, django_user_model):
    bidder_user = django_user_model.objects.create_user(
        username=f"intg_bidder_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    bidder = ensure_manor(bidder_user)

    gold_bar_tpl, _ = ItemTemplate.objects.get_or_create(
        key="gold_bar",
        defaults={
            "name": "金条",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    InventoryItem.objects.update_or_create(
        manor=bidder,
        template=gold_bar_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": 10},
    )

    auction_item = ItemTemplate.objects.create(
        key=f"intg_auction_item_{uuid.uuid4().hex[:8]}",
        name="集成测试拍卖物品",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=False,
        price=5000,
    )
    round_number = int(time.time())
    auction_round = AuctionRound.objects.create(
        round_number=round_number,
        status=AuctionRound.Status.ACTIVE,
        start_at=timezone.now() - timedelta(minutes=1),
        end_at=timezone.now() + timedelta(minutes=5),
    )
    slot = AuctionSlot.objects.create(
        round=auction_round,
        item_template=auction_item,
        quantity=1,
        starting_price=2,
        current_price=2,
        min_increment=1,
        status=AuctionSlot.Status.ACTIVE,
        config_key=auction_item.key,
        slot_index=0,
    )

    bid, _is_first = place_bid(bidder, slot.id, 5)
    stats = settle_auction_round(round_id=auction_round.id)

    bid.refresh_from_db()
    bid_item = InventoryItem.objects.get(
        manor=bidder,
        template=gold_bar_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    assert bid.status == AuctionBid.Status.WON
    assert stats["settled"] == 1
    assert stats["sold"] == 1
    assert bid_item.quantity == 5


@pytest.mark.django_db(transaction=True)
def test_integration_raid_start_and_retreat_flow(require_env_services, game_data, django_user_model):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_raid")

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(attacker, pool, seed=3)[0]
    guest = finalize_candidate(candidate)

    troop_template = TroopTemplate.objects.filter(key="archer").first() or TroopTemplate.objects.first()
    assert troop_template is not None

    PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=troop_template,
        defaults={"count": 200},
    )

    run = start_raid(attacker, defender, [guest.id], {troop_template.key: 10})
    run.refresh_from_db()
    assert run.status == RaidRun.Status.MARCHING

    request_raid_retreat(run)
    run.refresh_from_db()

    assert run.status == RaidRun.Status.RETREATED
    assert run.is_retreating is True


@pytest.mark.django_db(transaction=True)
def test_integration_complete_raid_task_finalizes_retreated_run(require_env_services, game_data, django_user_model):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_raid_task")

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(attacker, pool, seed=31)[0]
    guest = finalize_candidate(candidate)

    troop_template = TroopTemplate.objects.filter(key="archer").first() or TroopTemplate.objects.first()
    assert troop_template is not None

    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=troop_template,
        defaults={"count": 200},
    )

    run = start_raid(attacker, defender, [guest.id], {troop_template.key: 10})
    request_raid_retreat(run)

    run.refresh_from_db()
    troop.refresh_from_db()
    assert run.status == RaidRun.Status.RETREATED
    assert troop.count == 190

    run.return_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["return_at"])

    result = complete_raid_task.run(run.id)

    run.refresh_from_db()
    troop.refresh_from_db()
    guest.refresh_from_db()

    assert result == "completed"
    assert run.status == RaidRun.Status.COMPLETED
    assert run.completed_at is not None
    assert guest.status == guest.Status.IDLE
    assert troop.count == 200


@pytest.mark.django_db(transaction=True)
def test_integration_process_raid_battle_task_advances_due_marching_run(
    require_env_services, game_data, django_user_model
):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_raid_battle_task")

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(attacker, pool, seed=41)[0]
    guest = finalize_candidate(candidate)

    troop_template = TroopTemplate.objects.filter(key="archer").first() or TroopTemplate.objects.first()
    assert troop_template is not None

    PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=troop_template,
        defaults={"count": 200},
    )

    run = start_raid(attacker, defender, [guest.id], {troop_template.key: 10})
    run.battle_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["battle_at"])

    result = process_raid_battle_task.run(run.id)

    run.refresh_from_db()

    assert result == "completed"
    assert run.status == RaidRun.Status.RETURNING
    assert run.battle_report is not None
    assert run.is_attacker_victory is not None
    assert run.return_at is not None
    assert run.return_at > timezone.now()
    assert run.completed_at is None


@pytest.mark.django_db(transaction=True)
def test_integration_scout_refresh_dispatch_sets_external_dedup_gate(require_env_services):
    record_id = 10_000_000 + int(time.time())
    dedup_key = f"pvp:refresh_dispatch:scout:outbound:{record_id}"
    test_logger = logging.getLogger("tests.integration.scout_refresh_dispatch")
    cache.delete(dedup_key)

    ok = scout_refresh_command.try_dispatch_scout_refresh_task(
        complete_scout_task,
        record_id,
        "outbound",
        logger=test_logger,
    )

    assert ok is True
    assert cache.get(dedup_key) == "1"

    cache.delete(dedup_key)


@pytest.mark.django_db(transaction=True)
def test_integration_scout_refresh_dispatch_failure_rolls_back_dedup_gate(require_env_services):
    record_id = 20_000_000 + int(time.time())
    dedup_key = f"pvp:refresh_dispatch:scout:outbound:{record_id}"
    test_logger = logging.getLogger("tests.integration.scout_refresh_dispatch_failure")
    cache.delete(dedup_key)

    class _FailingTask:
        def apply_async(self, **_kwargs):
            raise RuntimeError("dispatch failed")

    ok = scout_refresh_command.try_dispatch_scout_refresh_task(
        _FailingTask(),
        record_id,
        "outbound",
        logger=test_logger,
    )

    assert ok is False
    assert cache.get(dedup_key) is None


@pytest.mark.django_db(transaction=True)
def test_integration_scout_refresh_sync_finalize_outbound_record(require_env_services, game_data, django_user_model):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_scout_outbound")
    scout_template, _ = TroopTemplate.objects.get_or_create(key="scout", defaults={"name": "探子"})
    PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 0},
    )

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=1.0,
        travel_time=600,
        complete_at=timezone.now() - timedelta(seconds=5),
    )

    refresh_scout_records(attacker, prefer_async=False)

    record.refresh_from_db()
    cooldown = ScoutCooldown.objects.get(attacker=attacker, defender=defender)

    assert record.status == ScoutRecord.Status.RETURNING
    assert record.is_success is True
    assert record.return_at is not None
    assert record.return_at > timezone.now()
    assert cooldown.cooldown_until > timezone.now()


@pytest.mark.django_db(transaction=True)
def test_integration_scout_refresh_sync_finalize_returning_record(require_env_services, game_data, django_user_model):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_scout_return")
    scout_template, _ = TroopTemplate.objects.get_or_create(key="scout", defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 0},
    )

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.RETURNING,
        scout_cost=1,
        success_rate=1.0,
        travel_time=60,
        complete_at=timezone.now() - timedelta(seconds=120),
        return_at=timezone.now() - timedelta(seconds=5),
        is_success=True,
        intel_data={"troop_description": "少量", "guest_count": 1, "avg_guest_level": 1, "asset_level": "一般"},
    )

    refresh_scout_records(attacker, prefer_async=False)

    record.refresh_from_db()
    troop.refresh_from_db()

    assert record.status == ScoutRecord.Status.SUCCESS
    assert record.completed_at is not None
    assert troop.count == 1


@pytest.mark.django_db(transaction=True)
def test_integration_start_scout_creates_record_under_external_services(
    require_env_services, game_data, django_user_model
):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_scout_start")
    scout_template, _ = TroopTemplate.objects.get_or_create(key="scout", defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 2},
    )

    record = start_scout(attacker, defender)

    troop.refresh_from_db()
    record.refresh_from_db()

    assert record.status == ScoutRecord.Status.SCOUTING
    assert record.complete_at > record.started_at
    assert troop.count == 1


@pytest.mark.django_db(transaction=True)
def test_integration_complete_scout_task_finalizes_outbound_record(require_env_services, game_data, django_user_model):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_scout_task_outbound")
    scout_template, _ = TroopTemplate.objects.get_or_create(key="scout", defaults={"name": "探子"})
    PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 0},
    )

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=1.0,
        travel_time=600,
        complete_at=timezone.now() - timedelta(seconds=5),
    )

    result = complete_scout_task.run(record.id)

    record.refresh_from_db()
    cooldown = ScoutCooldown.objects.get(attacker=attacker, defender=defender)

    assert result == "completed"
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.is_success is True
    assert record.return_at is not None
    assert record.return_at > timezone.now()
    assert cooldown.cooldown_until > timezone.now()


@pytest.mark.django_db(transaction=True)
def test_integration_complete_scout_return_task_finalizes_returning_record(
    require_env_services, game_data, django_user_model
):
    attacker, defender = _prepare_attack_ready_manors(django_user_model, prefix="intg_scout_task_return")
    scout_template, _ = TroopTemplate.objects.get_or_create(key="scout", defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 0},
    )

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.RETURNING,
        scout_cost=1,
        success_rate=1.0,
        travel_time=60,
        complete_at=timezone.now() - timedelta(seconds=120),
        return_at=timezone.now() - timedelta(seconds=5),
        is_success=True,
        intel_data={"troop_description": "少量", "guest_count": 1, "avg_guest_level": 1, "asset_level": "一般"},
    )

    result = complete_scout_return_task.run(record.id)

    record.refresh_from_db()
    troop.refresh_from_db()

    assert result == "completed"
    assert record.status == ScoutRecord.Status.SUCCESS
    assert record.completed_at is not None
    assert troop.count == 1
    assert Message.objects.filter(manor=attacker, title__startswith="侦察报告 - ").exists()


@pytest.mark.django_db(transaction=True)
def test_integration_mission_refresh_dispatch_sets_external_dedup_gate(require_env_services):
    run_id = 30_000_000 + int(time.time())
    dedup_key = f"mission:refresh_dispatch:{run_id}"
    cache.delete(dedup_key)

    ok = mission_execution.mission_followups.try_dispatch_mission_refresh_task(
        complete_mission_task,
        run_id,
        logger=mission_execution.logger,
        dedup_seconds=5,
    )

    assert ok is True
    assert cache.get(dedup_key) == "1"

    cache.delete(dedup_key)


@pytest.mark.django_db(transaction=True)
def test_integration_mission_refresh_dispatch_failure_rolls_back_dedup_gate(require_env_services):
    run_id = 40_000_000 + int(time.time())
    dedup_key = f"mission:refresh_dispatch:{run_id}"
    cache.delete(dedup_key)

    class _FailingTask:
        def apply_async(self, **_kwargs):
            raise RuntimeError("dispatch failed")

    ok = mission_execution.mission_followups.try_dispatch_mission_refresh_task(
        _FailingTask(),
        run_id,
        logger=mission_execution.logger,
        dedup_seconds=5,
    )

    assert ok is False
    assert cache.get(dedup_key) is None


@pytest.mark.django_db(transaction=True)
def test_integration_mission_launch_refresh_and_report_flow(
    require_env_services, game_data, mission_templates, django_user_model
):
    user = django_user_model.objects.create_user(
        username=f"intg_mission_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    manor = ensure_manor(user)
    manor.silver = max(int(manor.silver or 0), 50_000)
    manor.grain = max(int(manor.grain or 0), 50_000)
    manor.save(update_fields=["silver", "grain"])

    mission = MissionTemplate.objects.filter(guest_only=False, is_defense=False).first()
    if mission is None:
        pytest.skip("No offense mission available for integration coverage")

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=17)[0]
    guest = finalize_candidate(candidate)

    troop_template = TroopTemplate.objects.filter(key="archer").first() or TroopTemplate.objects.first()
    assert troop_template is not None

    PlayerTroop.objects.update_or_create(
        manor=manor,
        troop_template=troop_template,
        defaults={"count": 200},
    )

    run = launch_mission(manor, mission, [guest.id], {troop_template.key: 20})
    run.refresh_from_db()
    guest.refresh_from_db()

    assert run.status == MissionRun.Status.ACTIVE
    assert run.battle_report is not None
    assert guest.status == guest.Status.DEPLOYED

    run.return_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["return_at"])

    refresh_mission_runs(manor)

    run.refresh_from_db()
    guest.refresh_from_db()

    assert run.status == MissionRun.Status.COMPLETED
    assert run.completed_at is not None
    assert guest.status in [guest.Status.IDLE, guest.Status.INJURED]
    assert Message.objects.filter(manor=manor, title=f"{mission.name} 战报", battle_report=run.battle_report).exists()


@pytest.mark.django_db(transaction=True)
def test_integration_complete_mission_task_finalizes_due_run(
    require_env_services, game_data, mission_templates, django_user_model
):
    user = django_user_model.objects.create_user(
        username=f"intg_mission_task_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    manor = ensure_manor(user)
    manor.silver = max(int(manor.silver or 0), 50_000)
    manor.grain = max(int(manor.grain or 0), 50_000)
    manor.save(update_fields=["silver", "grain"])

    mission = MissionTemplate.objects.filter(guest_only=False, is_defense=False).first()
    if mission is None:
        pytest.skip("No offense mission available for integration coverage")

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=23)[0]
    guest = finalize_candidate(candidate)

    troop_template = TroopTemplate.objects.filter(key="archer").first() or TroopTemplate.objects.first()
    assert troop_template is not None

    PlayerTroop.objects.update_or_create(
        manor=manor,
        troop_template=troop_template,
        defaults={"count": 200},
    )

    run = launch_mission(manor, mission, [guest.id], {troop_template.key: 20})
    run.return_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["return_at"])

    result = complete_mission_task.run(run.id)

    run.refresh_from_db()
    guest.refresh_from_db()

    assert result == "completed"
    assert run.status == MissionRun.Status.COMPLETED
    assert run.completed_at is not None
    assert guest.status in [guest.Status.IDLE, guest.Status.INJURED]
    assert Message.objects.filter(manor=manor, title=f"{mission.name} 战报", battle_report=run.battle_report).exists()


@pytest.mark.django_db(transaction=True)
def test_integration_guest_recruitment_refresh_and_finalize_candidate_flow(
    require_env_services, game_data, django_user_model
):
    user = django_user_model.objects.create_user(
        username=f"intg_guest_recruit_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    recruitment = start_guest_recruitment(manor, pool, seed=77)
    recruitment.complete_at = timezone.now() - timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    completed = refresh_guest_recruitments(manor)

    recruitment.refresh_from_db()
    assert completed == 1
    assert recruitment.status == recruitment.Status.COMPLETED
    assert recruitment.result_count == manor.candidates.count()
    assert recruitment.result_count > 0

    candidate = manor.candidates.order_by("id").first()
    assert candidate is not None
    guest = finalize_candidate(candidate)

    assert guest.manor_id == manor.id
    assert not manor.candidates.filter(pk=candidate.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_integration_guild_application_approval_and_donation_flow(require_env_services, django_user_model):
    founder_user = django_user_model.objects.create_user(
        username=f"intg_guild_founder_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    applicant_user = django_user_model.objects.create_user(
        username=f"intg_guild_member_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    founder_manor = ensure_manor(founder_user)
    applicant_manor = ensure_manor(applicant_user)
    applicant_manor.silver = 10_000
    applicant_manor.save(update_fields=["silver"])

    gold_bar_tpl, _ = ItemTemplate.objects.get_or_create(
        key="gold_bar",
        defaults={
            "name": "金条",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    InventoryItem.objects.update_or_create(
        manor=founder_manor,
        template=gold_bar_tpl,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": GUILD_CREATION_COST["gold_bar"] + 2},
    )

    guild = create_guild(founder_user, name=f"帮测{uuid.uuid4().hex[:6]}", description="integration guild")
    application = apply_to_guild(applicant_user, guild, "求加入")
    approve_application(application, founder_user)

    applicant_member = GuildMember.objects.get(user=applicant_user)
    donate_resource(applicant_member, "silver", 1000)

    guild.refresh_from_db()
    applicant_member.refresh_from_db()
    application.refresh_from_db()

    assert application.status == "approved"
    assert applicant_member.is_active is True
    assert applicant_member.current_contribution == 1000 * CONTRIBUTION_RATES["silver"]
    assert guild.silver == 1000
    assert Message.objects.filter(manor=applicant_manor, title="入帮申请通过").exists()
    assert GuildAnnouncement.objects.filter(guild=guild, content__contains=applicant_manor.display_name).exists()
    assert GuildDonationLog.objects.filter(
        guild=guild,
        member=applicant_member,
        resource_type="silver",
        amount=1000,
    ).exists()
    assert GuildResourceLog.objects.filter(
        guild=guild,
        action="donation",
        silver_change=1000,
        related_user=applicant_user,
    ).exists()
    assert ResourceEvent.objects.filter(
        manor=applicant_manor,
        resource_type=ResourceType.SILVER,
        reason=ResourceEvent.Reason.GUILD_DONATION,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_integration_message_attachment_claim_flow(require_env_services, django_user_model):
    user = django_user_model.objects.create_user(
        username=f"intg_mail_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    manor = ensure_manor(user)

    item_key = f"intg_mail_item_{uuid.uuid4().hex[:8]}"
    ItemTemplate.objects.create(
        key=item_key,
        name="集成测试邮件道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=False,
    )

    message = Message.objects.create(
        manor=manor,
        kind=Message.Kind.REWARD,
        title="集成测试邮件",
        attachments={
            "resources": {ResourceType.SILVER: 50},
            "items": {item_key: 2},
        },
    )

    cache_key = CacheKeys.unread_count(manor.id)
    cache.set(cache_key, 999, timeout=30)

    claimed = claim_message_attachments(message)

    message.refresh_from_db()
    manor.refresh_from_db()
    item = InventoryItem.objects.get(
        manor=manor,
        template__key=item_key,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    assert claimed["silver"] == 50
    assert claimed[f"item_{item_key}"] == 2
    assert message.is_claimed is True
    assert message.is_read is True
    assert manor.silver >= 50
    assert item.quantity == 2
    assert cache.get(cache_key) is None

    event_exists = ResourceEvent.objects.filter(
        manor=manor,
        resource_type=ResourceType.SILVER,
        reason=ResourceEvent.Reason.ADMIN_ADJUST,
        note="邮件附件：集成测试邮件",
    ).exists()
    assert event_exists is True
