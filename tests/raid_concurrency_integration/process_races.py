from __future__ import annotations

import threading

import pytest
from django.db import connection
from django.utils import timezone

from gameplay.services.raid.combat import battle as combat_battle
from gameplay.services.raid.combat import runs as combat_runs
from tests.raid_concurrency_integration.support import (
    build_attacker_defender,
    configure_battle_side_effects,
    create_marching_run,
)


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_process_raid_battle_concurrent_requests_only_one_thread_executes(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker, defender = build_attacker_defender(
        django_user_model,
        attacker_username="raid_battle_concurrent_attacker",
        defender_username="raid_battle_concurrent_defender",
    )
    run = create_marching_run(attacker, defender, battle_due=True)

    executed_reports, dispatches = configure_battle_side_effects(monkeypatch, attacker=attacker, defender=defender)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_battle.process_raid_battle(local_run, now=timezone.now())
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    from gameplay.models import RaidRun

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
def test_refresh_raid_runs_concurrent_with_process_raid_battle_executes_only_once(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker, defender = build_attacker_defender(
        django_user_model,
        attacker_username="raid_refresh_battle_concurrent_attacker",
        defender_username="raid_refresh_battle_concurrent_defender",
    )
    run = create_marching_run(attacker, defender, battle_due=True)

    executed_reports, dispatches = configure_battle_side_effects(monkeypatch, attacker=attacker, defender=defender)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _process_worker() -> None:
        try:
            local_run = RaidRun.objects.get(pk=run.pk)
            barrier.wait(timeout=5)
            combat_battle.process_raid_battle(local_run, now=timezone.now())
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def _refresh_worker() -> None:
        try:
            local_attacker = type(attacker).objects.get(pk=attacker.pk)
            barrier.wait(timeout=5)
            combat_runs.refresh_raid_runs(local_attacker, prefer_async=False)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    from gameplay.models import RaidRun

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
