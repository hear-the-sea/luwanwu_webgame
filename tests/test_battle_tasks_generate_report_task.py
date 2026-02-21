import pytest
from types import SimpleNamespace

from gameplay.services.manor import ensure_manor


@pytest.mark.django_db
def test_generate_report_task_returns_none_when_manor_missing(monkeypatch, django_user_model):
    """Missing manor should not raise and should not retry."""
    from battle.tasks import generate_report_task

    called = {"retry": 0}

    def _no_retry(*_args, **_kwargs):
        called["retry"] += 1
        raise AssertionError("retry should not be called")

    monkeypatch.setattr(generate_report_task, "retry", _no_retry)

    # No manor created; use a very large id.
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
    """If MissionRun already has a battle_report, the task should short-circuit."""
    from battle.tasks import generate_report_task
    from battle.models import BattleReport
    from gameplay.models import MissionRun, MissionTemplate
    from django.utils import timezone

    user = django_user_model.objects.create_user(username="task_skip", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="m_task", name="Task", guest_only=True)

    now = timezone.now()
    report = BattleReport.objects.create(manor=manor, opponent_name="d", winner="attacker", starts_at=now, completed_at=now)
    run = MissionRun.objects.create(manor=manor, mission=mission, battle_report=report)

    monkeypatch.setattr(generate_report_task, "retry", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")))

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
def test_generate_report_task_does_not_retry_on_value_error(monkeypatch, django_user_model):
    """Business errors should be swallowed and not retried."""
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_value_error", password="pass")
    manor = ensure_manor(user)

    def _boom(**_kwargs):
        raise ValueError("bad input")

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
def test_generate_report_task_retries_on_unexpected_error(monkeypatch, django_user_model):
    """Unexpected errors should call celery retry."""
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_retry", password="pass")
    manor = ensure_manor(user)

    def _boom(**_kwargs):
        raise RuntimeError("boom")

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

    assert isinstance(state["exc"], RuntimeError)


@pytest.mark.django_db
def test_generate_report_task_defense_tolerates_invalid_enemy_technology(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task
    from gameplay.models import MissionTemplate

    user = django_user_model.objects.create_user(username="task_defense_bad_tech", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(
        key="m_task_defense_bad_tech",
        name="DefenseTask",
        is_defense=True,
        enemy_technology="bad-config",
        enemy_troops="bad-troops",
        enemy_guests="bad-guests",
    )

    level_state = {}
    guest_keys_state = {}

    def _build_named_ai_guests(keys, level):
        guest_keys_state["keys"] = keys
        level_state["level"] = level
        return []

    def _fake_simulate_report(**kwargs):
        assert kwargs["troop_loadout"] == {}
        assert kwargs["attacker_tech_levels"] == {}
        assert kwargs["attacker_guest_bonuses"] is None
        assert kwargs["attacker_guest_skills"] is None
        return SimpleNamespace(pk=321)

    monkeypatch.setattr("battle.combatants.build_named_ai_guests", _build_named_ai_guests)
    monkeypatch.setattr("battle.tasks.simulate_report", _fake_simulate_report)
    monkeypatch.setattr(generate_report_task, "retry", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")))

    got = generate_report_task.run(
        manor_id=manor.id,
        mission_id=mission.id,
        run_id=None,
        guest_ids=[],
        troop_loadout={},
        battle_type="task",
    )

    assert got == 321
    assert level_state["level"] == 50
    assert guest_keys_state["keys"] == []
