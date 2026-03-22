from types import SimpleNamespace

import pytest
from django.db import DatabaseError

from core.exceptions import BattlePreparationError
from gameplay.services.manor.core import ensure_manor


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

    monkeypatch.setattr(
        generate_report_task,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

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
    """Business errors should be swallowed and not retried."""
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
    """Infrastructure errors should call celery retry."""
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
    """Programming errors should bubble up instead of being silently retried."""
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_retry", password="pass")
    manor = ensure_manor(user)

    def _boom(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("battle.tasks.simulate_report", _boom)

    monkeypatch.setattr(
        generate_report_task,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type="skirmish",
        )


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
        assert kwargs["validate_attacker_troop_capacity"] is False
        return SimpleNamespace(pk=321)

    monkeypatch.setattr("battle.combatants_pkg.build_named_ai_guests", _build_named_ai_guests)
    monkeypatch.setattr("battle.tasks.simulate_report", _fake_simulate_report)
    monkeypatch.setattr(
        generate_report_task,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

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


@pytest.mark.django_db
def test_generate_report_task_uses_mission_run_guest_snapshot(monkeypatch, django_user_model):
    from django.utils import timezone

    from battle.models import BattleReport
    from battle.tasks import generate_report_task
    from gameplay.models import MissionRun, MissionTemplate
    from guests.models import Guest, GuestTemplate

    user = django_user_model.objects.create_user(username="task_snapshot_user", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="m_task_snapshot", name="Task Snapshot", guest_only=True)
    template = GuestTemplate.objects.create(
        key="task_snapshot_guest_tpl",
        name="快照门客",
        archetype="military",
        rarity="green",
        base_attack=120,
        base_intellect=90,
        base_defense=100,
        base_agility=90,
        base_luck=50,
        base_hp=1500,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        level=20,
        force=300,
        intellect=120,
        defense_stat=130,
        agility=110,
        current_hp=800,
    )
    stats = guest.stat_block()
    run = MissionRun.objects.create(
        manor=manor,
        mission=mission,
        guest_snapshots=[
            {
                "guest_id": guest.id,
                "template_key": template.key,
                "display_name": guest.display_name,
                "rarity": guest.rarity,
                "status": "deployed",
                "level": 20,
                "force": 300,
                "intellect": 120,
                "defense_stat": 130,
                "agility": 110,
                "luck": 50,
                "attack": int(stats["attack"]),
                "defense": int(stats["defense"]),
                "max_hp": guest.max_hp,
                "current_hp": 800,
                "troop_capacity": int(getattr(guest, "troop_capacity", 0) or 0),
                "skill_keys": [],
            }
        ],
    )

    # 报名后实时属性变化，不应影响战报生成快照
    guest.level = 99
    guest.force = 9999
    guest.save(update_fields=["level", "force"])

    captured = {}

    def _fake_simulate_report(**kwargs):
        attacker_guests = kwargs.get("attacker_guests") or []
        assert attacker_guests
        captured["level"] = attacker_guests[0].level
        captured["force"] = attacker_guests[0].force
        captured["guest_id"] = attacker_guests[0].id
        now = timezone.now()
        return BattleReport.objects.create(
            manor=manor,
            opponent_name="snapshot",
            winner="attacker",
            starts_at=now,
            completed_at=now,
        )

    monkeypatch.setattr("battle.tasks.simulate_report", _fake_simulate_report)
    monkeypatch.setattr(
        generate_report_task,
        "retry",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    report_id = generate_report_task.run(
        manor_id=manor.id,
        mission_id=mission.id,
        run_id=run.id,
        guest_ids=[guest.id],
        troop_loadout={},
        battle_type="task",
    )

    assert report_id is not None
    assert captured["level"] == 20
    assert captured["force"] == 300
    assert captured["guest_id"] == guest.id
