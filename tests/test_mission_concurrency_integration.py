from __future__ import annotations

import threading
import uuid

import pytest
from django.db import connection

import gameplay.services.missions_impl.execution as mission_execution
from core.exceptions import MissionCannotRetreatError, MissionGuestSelectionError
from gameplay.models import MissionRun, MissionTemplate
from gameplay.services.manor.core import ensure_manor
from gameplay.services.missions import launch_mission, request_retreat
from guests.models import Guest, GuestStatus, GuestTemplate


def _select_guest_only_offense_mission() -> MissionTemplate | None:
    return MissionTemplate.objects.filter(is_defense=False, guest_only=True).order_by("id").first()


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_launch_mission_concurrent_requests_allow_only_one_active_run_for_same_guest(
    game_data, mission_templates, django_user_model, monkeypatch
):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    user = django_user_model.objects.create_user(
        username=f"mission_launch_concurrent_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    manor = ensure_manor(user)

    mission = _select_guest_only_offense_mission()
    if mission is None:
        pytest.skip("No guest-only offense mission available for concurrency coverage")
    if mission.daily_limit < 2:
        mission.daily_limit = 2
        mission.save(update_fields=["daily_limit"])

    guest_template = GuestTemplate.objects.first()
    if guest_template is None:
        pytest.skip("No guest template available")

    guest = Guest.objects.create(
        manor=manor,
        template=guest_template,
        level=20,
        status=GuestStatus.IDLE,
        custom_name="mission_concurrency_guest",
    )

    monkeypatch.setattr(mission_execution, "_import_launch_post_action_tasks", lambda: (None, None))
    monkeypatch.setattr(mission_execution, "_try_prepare_launch_report", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mission_execution, "_dispatch_complete_mission_task", lambda *_args, **_kwargs: None)

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker(seed: int) -> None:
        try:
            local_manor = type(manor).objects.get(pk=manor.pk)
            local_mission = MissionTemplate.objects.get(pk=mission.pk)
            barrier.wait(timeout=5)
            run = launch_mission(local_manor, local_mission, [guest.pk], {}, seed=seed)
            results.append(run.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(101,)),
        threading.Thread(target=_worker, args=(202,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    guest.refresh_from_db()

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], MissionGuestSelectionError)
    assert "部分门客不可用或已离开庄园" in str(errors[0])
    assert MissionRun.objects.filter(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE).count() == 1
    assert guest.status == GuestStatus.DEPLOYED


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_request_retreat_concurrent_requests_allow_only_one_transition(
    game_data, mission_templates, django_user_model, monkeypatch
):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    user = django_user_model.objects.create_user(
        username=f"mission_retreat_concurrent_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    manor = ensure_manor(user)

    mission = _select_guest_only_offense_mission()
    if mission is None:
        pytest.skip("No guest-only offense mission available for concurrency coverage")

    run = MissionRun.objects.create(
        manor=manor,
        mission=mission,
        guest_snapshots=[],
        troop_loadout={},
        travel_time=300,
    )

    monkeypatch.setattr(mission_execution, "schedule_mission_completion", lambda *_args, **_kwargs: None)

    barrier = threading.Barrier(2)
    successes: list[int] = []
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_run = MissionRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            request_retreat(local_run)
            successes.append(local_run.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    run.refresh_from_db()

    assert len(successes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], MissionCannotRetreatError)
    assert "任务已在撤退中" in str(errors[0])
    assert run.status == MissionRun.Status.ACTIVE
    assert run.is_retreating is True
    assert run.return_at is not None
