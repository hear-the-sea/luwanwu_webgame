from __future__ import annotations

import pytest
from django.db import DatabaseError

from core.exceptions import BattlePreparationError
from gameplay.services.manor.core import ensure_manor
from tests.battle_tasks_generate_report_task.support import assert_no_retry


@pytest.mark.django_db
def test_generate_report_task_returns_none_when_manor_missing(monkeypatch):
    from battle.tasks import generate_report_task

    called = {"retry": 0}

    def _no_retry(*_args, **_kwargs):
        called["retry"] += 1
        raise AssertionError("retry should not be called")

    monkeypatch.setattr(generate_report_task, "retry", _no_retry)

    result = generate_report_task.run(
        manor_id=999999,
        mission_id=None,
        run_id=None,
        guest_ids=[],
        troop_loadout={},
        battle_type="skirmish",
    )
    assert result is None
    assert called["retry"] == 0


@pytest.mark.django_db
def test_generate_report_task_skips_when_run_already_has_report(monkeypatch, django_user_model):
    from django.utils import timezone

    from battle.models import BattleReport
    from battle.tasks import generate_report_task
    from gameplay.models import MissionRun, MissionTemplate

    user = django_user_model.objects.create_user(username="task_skip", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="m_task", name="Task", guest_only=True)

    now = timezone.now()
    report = BattleReport.objects.create(
        manor=manor, opponent_name="d", winner="attacker", starts_at=now, completed_at=now
    )
    run = MissionRun.objects.create(manor=manor, mission=mission, battle_report=report)

    assert_no_retry(monkeypatch)

    got = generate_report_task.run(
        manor_id=manor.id,
        mission_id=mission.id,
        run_id=run.id,
        guest_ids=[],
        troop_loadout={},
        battle_type="skirmish",
    )
    assert got == report.id


@pytest.mark.django_db
def test_generate_report_task_does_not_retry_on_game_error(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_value_error", password="pass")
    manor = ensure_manor(user)

    def _boom(**_kwargs):
        raise BattlePreparationError("bad input")

    monkeypatch.setattr("battle.tasks.simulate_report", _boom)

    called = {"retry": 0}

    def _no_retry(*_args, **_kwargs):
        called["retry"] += 1
        raise AssertionError("retry should not be called")

    monkeypatch.setattr(generate_report_task, "retry", _no_retry)

    got = generate_report_task.run(
        manor_id=manor.id,
        mission_id=None,
        run_id=None,
        guest_ids=[],
        troop_loadout={},
        battle_type="skirmish",
    )
    assert got is None
    assert called["retry"] == 0


@pytest.mark.django_db
def test_generate_report_task_database_error_retries(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_database_error", password="pass")
    manor = ensure_manor(user)

    def _boom(**_kwargs):
        raise DatabaseError("db down")

    monkeypatch.setattr("battle.tasks.simulate_report", _boom)

    state = {"exc": None}

    def _retry(exc):
        state["exc"] = exc
        raise RuntimeError("retried")

    monkeypatch.setattr(generate_report_task, "retry", _retry)

    with pytest.raises(RuntimeError, match="retried"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type="skirmish",
        )

    assert isinstance(state["exc"], DatabaseError)


@pytest.mark.django_db
def test_generate_report_task_unexpected_error_bubbles_up(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_retry", password="pass")
    manor = ensure_manor(user)

    def _boom(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("battle.tasks.simulate_report", _boom)
    assert_no_retry(monkeypatch)

    with pytest.raises(RuntimeError, match="boom"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type="skirmish",
        )
