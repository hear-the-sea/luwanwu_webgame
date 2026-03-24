from __future__ import annotations

import logging
import time
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from kombu.exceptions import OperationalError

from battle.models import TroopTemplate
from gameplay.models import Message, PlayerTroop, RaidRun, ScoutCooldown, ScoutRecord
from gameplay.services.raid import refresh_scout_records, request_raid_retreat
from gameplay.services.raid import scout_refresh as scout_refresh_command
from gameplay.services.raid import start_raid, start_scout
from gameplay.tasks import complete_raid_task
from gameplay.tasks.pvp import complete_scout_return_task, complete_scout_task, process_raid_battle_task
from guests.models import GuestStatus, RecruitmentPool
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate
from tests.integration.external_services_support import prepare_attack_ready_manors

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("load_guest_data", "load_troop_data")]


@pytest.mark.django_db(transaction=True)
def test_integration_raid_start_and_retreat_flow(require_env_services, game_data, django_user_model):
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_raid")

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
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_raid_task")

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
    assert guest.status == GuestStatus.IDLE
    assert troop.count == 200


@pytest.mark.django_db(transaction=True)
def test_integration_process_raid_battle_task_advances_due_marching_run(
    require_env_services, game_data, django_user_model
):
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_raid_battle_task")

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
            raise OperationalError("dispatch failed")

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
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_scout_outbound")
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
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_scout_return")
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
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_scout_start")
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
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_scout_task_outbound")
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
    attacker, defender = prepare_attack_ready_manors(django_user_model, prefix="intg_scout_task_return")
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
