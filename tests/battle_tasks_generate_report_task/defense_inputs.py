from __future__ import annotations

import pytest

from gameplay.services.manor.core import ensure_manor
from tests.battle_tasks_generate_report_task.support import assert_no_retry


@pytest.mark.django_db
def test_generate_report_task_defense_rejects_invalid_enemy_technology(monkeypatch, django_user_model):
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
    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission enemy technology"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=mission.id,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type="task",
        )


@pytest.mark.django_db
def test_generate_report_task_defense_rejects_invalid_enemy_guest_mapping_skills(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task
    from gameplay.models import MissionTemplate

    user = django_user_model.objects.create_user(username="task_defense_bad_guest_skills", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(
        key="m_task_defense_bad_guest_skills",
        name="DefenseTaskGuestSkills",
        is_defense=True,
        enemy_technology={},
        enemy_troops={},
        enemy_guests=[{"key": "enemy_guest", "skills": "bad-skills"}],
    )

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission guest config skills"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=mission.id,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type="task",
        )


@pytest.mark.django_db
def test_generate_report_task_defense_rejects_invalid_defender_troop_loadout(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task
    from gameplay.models import MissionTemplate

    user = django_user_model.objects.create_user(username="task_defense_bad_defender_loadout", password="pass")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(
        key="m_task_defense_bad_defender_loadout",
        name="DefenseTaskDefenderLoadout",
        is_defense=True,
        enemy_technology={},
        enemy_troops={},
        enemy_guests=[],
    )

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission troop loadout quantity"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=mission.id,
            run_id=None,
            guest_ids=[],
            troop_loadout={"archer": "bad"},
            battle_type="task",
        )
