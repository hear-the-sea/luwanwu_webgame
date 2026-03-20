from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from core.exceptions import RaidStartError, ScoutRetreatStateError
from gameplay.models import RaidRun
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.combat import runs as combat_runs


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_start_raid_concurrent_requests_respect_limit_inside_lock(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(username="raid_concurrent_attacker", password="pass123")
    defender_user = django_user_model.objects.create_user(username="raid_concurrent_defender", password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    monkeypatch.setattr(combat_runs.PVPConstants, "RAID_MAX_CONCURRENT", 1)
    monkeypatch.setattr(
        combat_runs,
        "_validate_and_normalize_raid_inputs",
        lambda *_args, **_kwargs: ([101], {"inf": 1}),
    )
    monkeypatch.setattr(combat_runs, "_recheck_can_attack_target", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(combat_runs, "_load_and_validate_attacker_guests", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(combat_runs, "_normalize_and_validate_raid_loadout", lambda *_args, **_kwargs: {"inf": 1})
    monkeypatch.setattr(combat_runs, "_deduct_troops", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "calculate_raid_travel_time", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(combat_runs, "_send_raid_incoming_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "_dispatch_raid_battle_task", lambda *_args, **_kwargs: None)

    def _create_run(attacker_locked, defender_locked, guests, loadout, travel_time):
        now = timezone.now()
        run = RaidRun.objects.create(
            attacker=attacker_locked,
            defender=defender_locked,
            troop_loadout=loadout,
            status=RaidRun.Status.MARCHING,
            travel_time=travel_time,
            battle_at=now + timedelta(seconds=travel_time),
            return_at=now + timedelta(seconds=travel_time * 2),
        )
        run.guests.set(guests)
        return run

    monkeypatch.setattr(combat_runs, "_create_raid_run_record", _create_run)

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker():
        try:
            barrier.wait(timeout=5)
            run = combat_runs.start_raid(attacker, defender, [101], {"inf": 1})
            results.append(run.id)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RaidStartError)
    assert "同时最多进行" in str(errors[0])
    assert RaidRun.objects.filter(attacker=attacker, status=RaidRun.Status.MARCHING).count() == 1


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_request_raid_retreat_concurrent_requests_allow_only_one_transition(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="raid_retreat_concurrent_attacker", password="pass123"
    )
    defender_user = django_user_model.objects.create_user(
        username="raid_retreat_concurrent_defender", password="pass123"
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    now = timezone.now()
    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=now + timedelta(seconds=60),
        return_at=now + timedelta(seconds=120),
    )

    monkeypatch.setattr(combat_runs, "_schedule_raid_retreat_completion", lambda *_args, **_kwargs: None)

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker():
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_runs.request_raid_retreat(local_run)
            results.append(local_run.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    run.refresh_from_db()

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ScoutRetreatStateError)
    assert "当前状态无法撤退" in str(errors[0])
    assert run.status == RaidRun.Status.RETREATED
    assert run.is_retreating is True
    assert run.return_at is not None
