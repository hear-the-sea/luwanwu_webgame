from __future__ import annotations

import pytest

from gameplay.services.manor.core import ensure_manor
from tests.battle_tasks_generate_report_task.support import assert_no_retry


@pytest.mark.django_db
def test_generate_report_task_offense_rejects_invalid_troop_loadout(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_offense_bad_loadout", password="pass")
    manor = ensure_manor(user)

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission troop loadout"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout="bad-loadout",
            battle_type="skirmish",
        )


@pytest.mark.django_db
def test_generate_report_task_offense_rejects_invalid_defender_setup(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_offense_bad_defender_setup", password="pass")
    manor = ensure_manor(user)

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission mapping payload"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            defender_setup="bad-defender-setup",
            battle_type="skirmish",
        )


@pytest.mark.django_db
def test_generate_report_task_rejects_invalid_guest_ids_payload(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_bad_guest_ids", password="pass")
    manor = ensure_manor(user)

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission guest_ids"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids="bad-guest-ids",
            troop_loadout={},
            battle_type="skirmish",
        )


@pytest.mark.django_db
def test_generate_report_task_rejects_invalid_travel_seconds(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_bad_travel_seconds", password="pass")
    manor = ensure_manor(user)

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission travel_seconds"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type="skirmish",
            travel_seconds=-1,
        )


@pytest.mark.django_db
def test_generate_report_task_rejects_blank_battle_type(monkeypatch, django_user_model):
    from battle.tasks import generate_report_task

    user = django_user_model.objects.create_user(username="task_blank_battle_type", password="pass")
    manor = ensure_manor(user)

    assert_no_retry(monkeypatch)

    with pytest.raises(AssertionError, match="invalid mission battle_type"):
        generate_report_task.run(
            manor_id=manor.id,
            mission_id=None,
            run_id=None,
            guest_ids=[],
            troop_loadout={},
            battle_type=" ",
        )
