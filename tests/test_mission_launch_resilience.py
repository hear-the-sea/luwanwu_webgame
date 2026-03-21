import logging

import pytest

import gameplay.services.missions_impl.execution as mission_execution
from gameplay.models import MissionRun, MissionTemplate
from guests.models import Guest, GuestStatus, GuestTemplate


def _create_launch_guest(manor):
    template = GuestTemplate.objects.first()
    if template is None:
        pytest.skip("No guest template available")

    return Guest.objects.create(
        manor=manor,
        template=template,
        level=20,
        status=GuestStatus.IDLE,
        custom_name="mission_resilience_guest",
    )


def _select_offense_mission():
    mission = MissionTemplate.objects.filter(is_defense=False).order_by("-guest_only", "id").first()
    if mission is None:
        pytest.skip("No offense mission available")
    return mission


@pytest.mark.django_db(transaction=True)
def test_launch_mission_survives_dispatch_failure(game_data, mission_templates, manor_with_troops, monkeypatch, caplog):
    manor = manor_with_troops
    mission = _select_offense_mission()
    guest = _create_launch_guest(manor)

    monkeypatch.setattr(
        mission_execution.mission_followups,
        "import_launch_post_action_tasks",
        lambda **_kwargs: (object(), object()),
    )
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "dispatch_or_sync_launch_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "schedule_mission_completion_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dispatch backend unavailable")),
    )

    caplog.set_level(logging.ERROR, logger=mission_execution.__name__)

    run = mission_execution.launch_mission(manor, mission, [guest.id], {})

    persisted_run = MissionRun.objects.get(pk=run.pk)
    guest.refresh_from_db()

    assert persisted_run.pk is not None
    assert persisted_run.status == MissionRun.Status.ACTIVE
    assert guest.status == GuestStatus.DEPLOYED
    assert any(
        getattr(record, "degraded", False) and getattr(record, "component", "") == "mission_completion_dispatch"
        for record in caplog.records
    )


@pytest.mark.django_db(transaction=True)
def test_launch_mission_survives_report_failure(game_data, mission_templates, manor_with_troops, monkeypatch, caplog):
    manor = manor_with_troops
    mission = _select_offense_mission()
    guest = _create_launch_guest(manor)

    monkeypatch.setattr(
        mission_execution.mission_followups,
        "import_launch_post_action_tasks",
        lambda **_kwargs: (object(), object()),
    )
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "dispatch_or_sync_launch_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("report generation exploded")),
    )
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "schedule_mission_completion_task",
        lambda *_args, **_kwargs: None,
    )

    caplog.set_level(logging.ERROR, logger=mission_execution.__name__)

    run = mission_execution.launch_mission(manor, mission, [guest.id], {})

    persisted_run = MissionRun.objects.get(pk=run.pk)
    guest.refresh_from_db()

    assert persisted_run.pk is not None
    assert persisted_run.status == MissionRun.Status.ACTIVE
    assert persisted_run.battle_report is None
    assert guest.status == GuestStatus.DEPLOYED
    assert any(
        getattr(record, "degraded", False) and getattr(record, "component", "") == "mission_launch_report"
        for record in caplog.records
    )


@pytest.mark.django_db(transaction=True)
def test_launch_mission_does_not_trigger_refresh_command(game_data, mission_templates, manor_with_troops, monkeypatch):
    manor = manor_with_troops
    mission = _select_offense_mission()
    guest = _create_launch_guest(manor)

    monkeypatch.setattr(
        mission_execution.mission_followups,
        "import_launch_post_action_tasks",
        lambda **_kwargs: (object(), object()),
    )
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "dispatch_or_sync_launch_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "schedule_mission_completion_task",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mission_execution,
        "refresh_mission_runs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("launch should not refresh due runs")),
    )

    run = mission_execution.launch_mission(manor, mission, [guest.id], {})

    assert MissionRun.objects.filter(pk=run.pk, status=MissionRun.Status.ACTIVE).exists()
