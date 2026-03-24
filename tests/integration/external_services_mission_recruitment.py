from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from kombu.exceptions import OperationalError

import gameplay.services.missions_impl.execution as mission_execution
from battle.models import TroopTemplate
from gameplay.models import Message, MissionRun, MissionTemplate, PlayerTroop
from gameplay.services.manor.core import ensure_manor
from gameplay.services.missions import launch_mission, refresh_mission_runs
from gameplay.tasks import complete_mission_task
from guests.models import GuestRecruitment, GuestStatus, RecruitmentPool
from guests.services.recruitment import recruit_guest, refresh_guest_recruitments, start_guest_recruitment
from guests.services.recruitment_guests import finalize_candidate

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("load_guest_data", "load_troop_data")]


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
            raise OperationalError("dispatch failed")

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
    assert guest.status == GuestStatus.DEPLOYED

    run.return_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["return_at"])

    refresh_mission_runs(manor)

    run.refresh_from_db()
    guest.refresh_from_db()

    assert run.status == MissionRun.Status.COMPLETED
    assert run.completed_at is not None
    assert guest.status in [GuestStatus.IDLE, GuestStatus.INJURED]
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
    assert guest.status in [GuestStatus.IDLE, GuestStatus.INJURED]
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
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert recruitment.result_count == manor.candidates.count()
    assert recruitment.result_count > 0

    candidate = manor.candidates.order_by("id").first()
    assert candidate is not None
    guest = finalize_candidate(candidate)

    assert guest.manor_id == manor.id
    assert not manor.candidates.filter(pk=candidate.pk).exists()
