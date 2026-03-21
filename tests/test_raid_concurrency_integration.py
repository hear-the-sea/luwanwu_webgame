from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from battle.models import BattleReport
from core.exceptions import RaidRetreatStateError, RaidStartError
from gameplay.models import RaidRun
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.combat import battle as combat_battle
from gameplay.services.raid.combat import runs as combat_runs
from guests.models import Guest, GuestStatus, GuestTemplate


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
    assert isinstance(errors[0], RaidRetreatStateError)
    assert "当前状态无法撤退" in str(errors[0])
    assert run.status == RaidRun.Status.RETREATED
    assert run.is_retreating is True
    assert run.return_at is not None


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_process_raid_battle_concurrent_requests_only_one_thread_executes(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="raid_battle_concurrent_attacker", password="pass123"
    )
    defender_user = django_user_model.objects.create_user(
        username="raid_battle_concurrent_defender", password="pass123"
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=timezone.now() - timedelta(seconds=1),
        return_at=timezone.now() + timedelta(seconds=60),
    )

    executed_reports: list[int] = []
    dispatches: list[int] = []
    side_effect_lock = threading.Lock()

    monkeypatch.setattr(combat_battle, "_lock_battle_manors", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_battle, "_get_defender_battle_block_reason", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "apply_defender_troop_losses", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_raid_loot_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_prestige_changes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_defeat_protection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_capture_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_salvage_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_send_raid_battle_messages", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_dismiss_marching_raids_if_protected", lambda *_args, **_kwargs: None)

    def _fake_execute(locked_run):
        report = BattleReport.objects.create(
            manor=locked_run.attacker,
            opponent_name=locked_run.defender.display_name,
            battle_type="raid",
            attacker_team=[],
            attacker_troops={},
            defender_team=[],
            defender_troops={},
            rounds=[],
            losses={},
            drops={},
            winner="attacker",
            starts_at=timezone.now(),
            completed_at=timezone.now(),
        )
        with side_effect_lock:
            executed_reports.append(report.pk)
        return report

    def _fake_dispatch(locked_run, *, now=None):
        del now
        with side_effect_lock:
            dispatches.append(locked_run.pk)

    monkeypatch.setattr(combat_battle, "_execute_raid_battle", _fake_execute)
    monkeypatch.setattr(combat_battle, "_dispatch_complete_raid_task", _fake_dispatch)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_battle.process_raid_battle(local_run, now=timezone.now())
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    run.refresh_from_db()

    assert errors == []
    assert len(executed_reports) == 1
    assert len(dispatches) == 1
    assert run.status == RaidRun.Status.RETURNING
    assert run.is_attacker_victory is True
    assert run.battle_report_id == executed_reports[0]


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_finalize_raid_concurrent_requests_only_one_thread_completes(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="raid_finalize_concurrent_attacker", password="pass123"
    )
    defender_user = django_user_model.objects.create_user(
        username="raid_finalize_concurrent_defender", password="pass123"
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    template = GuestTemplate.objects.first()
    if template is None:
        pytest.skip("No guest template available")

    guest = Guest.objects.create(
        manor=attacker,
        template=template,
        level=20,
        status=GuestStatus.DEPLOYED,
        custom_name="raid_finalize_concurrent_guest",
    )
    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.RETURNING,
        travel_time=60,
        return_at=timezone.now() - timedelta(seconds=1),
    )
    run.guests.add(guest)

    returned: list[int] = []
    returned_lock = threading.Lock()

    def _record_returned(locked_run) -> None:
        with returned_lock:
            returned.append(locked_run.pk)

    monkeypatch.setattr(combat_runs, "_return_surviving_troops", _record_returned)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_runs.finalize_raid(local_run, now=timezone.now())
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    run.refresh_from_db()
    guest.refresh_from_db()

    assert errors == []
    assert returned == [run.pk]
    assert run.status == RaidRun.Status.COMPLETED
    assert run.completed_at is not None
    assert guest.status == GuestStatus.IDLE


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_refresh_raid_runs_concurrent_with_process_raid_battle_executes_only_once(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="raid_refresh_battle_concurrent_attacker",
        password="pass123",
    )
    defender_user = django_user_model.objects.create_user(
        username="raid_refresh_battle_concurrent_defender",
        password="pass123",
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=timezone.now() - timedelta(seconds=1),
        return_at=timezone.now() + timedelta(seconds=60),
    )

    executed_reports: list[int] = []
    dispatches: list[int] = []
    side_effect_lock = threading.Lock()

    monkeypatch.setattr(combat_battle, "_lock_battle_manors", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_battle, "_get_defender_battle_block_reason", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "apply_defender_troop_losses", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_raid_loot_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_prestige_changes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_defeat_protection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_capture_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_salvage_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_send_raid_battle_messages", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_dismiss_marching_raids_if_protected", lambda *_args, **_kwargs: None)

    def _fake_execute(locked_run):
        report = BattleReport.objects.create(
            manor=locked_run.attacker,
            opponent_name=locked_run.defender.display_name,
            battle_type="raid",
            attacker_team=[],
            attacker_troops={},
            defender_team=[],
            defender_troops={},
            rounds=[],
            losses={},
            drops={},
            winner="attacker",
            starts_at=timezone.now(),
            completed_at=timezone.now(),
        )
        with side_effect_lock:
            executed_reports.append(report.pk)
        return report

    def _fake_dispatch(locked_run, *, now=None):
        del now
        with side_effect_lock:
            dispatches.append(locked_run.pk)

    monkeypatch.setattr(combat_battle, "_execute_raid_battle", _fake_execute)
    monkeypatch.setattr(combat_battle, "_dispatch_complete_raid_task", _fake_dispatch)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _process_worker() -> None:
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_battle.process_raid_battle(local_run, now=timezone.now())
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    def _refresh_worker() -> None:
        try:
            local_attacker = type(attacker).objects.get(pk=attacker.pk)
            barrier.wait(timeout=5)
            combat_runs.refresh_raid_runs(local_attacker, prefer_async=False)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_process_worker),
        threading.Thread(target=_refresh_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    run.refresh_from_db()

    assert errors == []
    assert len(executed_reports) == 1
    assert len(dispatches) == 1
    assert run.status == RaidRun.Status.RETURNING
    assert run.is_attacker_victory is True
    assert run.battle_report_id == executed_reports[0]


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_refresh_raid_runs_concurrent_with_finalize_raid_completes_only_once(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="raid_refresh_finalize_concurrent_attacker",
        password="pass123",
    )
    defender_user = django_user_model.objects.create_user(
        username="raid_refresh_finalize_concurrent_defender",
        password="pass123",
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    template = GuestTemplate.objects.first()
    if template is None:
        pytest.skip("No guest template available")

    guest = Guest.objects.create(
        manor=attacker,
        template=template,
        level=20,
        status=GuestStatus.DEPLOYED,
        custom_name="raid_refresh_finalize_guest",
    )
    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.RETURNING,
        travel_time=60,
        return_at=timezone.now() - timedelta(seconds=1),
    )
    run.guests.add(guest)

    returned: list[int] = []
    returned_lock = threading.Lock()

    def _record_returned(locked_run) -> None:
        with returned_lock:
            returned.append(locked_run.pk)

    monkeypatch.setattr(combat_runs, "_return_surviving_troops", _record_returned)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _finalize_worker() -> None:
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_runs.finalize_raid(local_run, now=timezone.now())
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    def _refresh_worker() -> None:
        try:
            local_attacker = type(attacker).objects.get(pk=attacker.pk)
            barrier.wait(timeout=5)
            combat_runs.refresh_raid_runs(local_attacker, prefer_async=False)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_finalize_worker),
        threading.Thread(target=_refresh_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    run.refresh_from_db()
    guest.refresh_from_db()

    assert errors == []
    assert returned == [run.pk]
    assert run.status == RaidRun.Status.COMPLETED
    assert run.completed_at is not None
    assert guest.status == GuestStatus.IDLE
