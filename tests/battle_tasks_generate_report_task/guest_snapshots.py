from __future__ import annotations

import pytest

from gameplay.services.manor.core import ensure_manor
from tests.battle_tasks_generate_report_task.support import assert_no_retry


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
    assert_no_retry(monkeypatch)

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


@pytest.mark.django_db
def test_generate_report_task_rejects_invalid_guest_snapshots_payload(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task
    from gameplay.models import MissionRun, MissionTemplate

    user = django_user_model.objects.create_user(username="task_bad_snapshot_payload", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="m_task_bad_snapshot_payload", name="Task Snapshot Payload")
    run = MissionRun.objects.create(manor=manor, mission=mission, guest_snapshots="bad-snapshots")

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission guest_snapshots payload"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=mission.id,
            run_id=run.id,
            guest_ids=[],
            troop_loadout={},
            battle_type="task",
        )


@pytest.mark.django_db
def test_generate_report_task_rejects_invalid_guest_snapshot_entry(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task
    from gameplay.models import MissionRun, MissionTemplate

    user = django_user_model.objects.create_user(username="task_bad_snapshot_entry", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="m_task_bad_snapshot_entry", name="Task Snapshot Entry")
    run = MissionRun.objects.create(manor=manor, mission=mission, guest_snapshots=["bad-entry"])

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission guest_snapshot entry"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=mission.id,
            run_id=run.id,
            guest_ids=[],
            troop_loadout={},
            battle_type="task",
        )
