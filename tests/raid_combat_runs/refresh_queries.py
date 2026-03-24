from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import IntegrityError
from django.utils import timezone

from gameplay.services.raid.combat import battle as combat_battle
from gameplay.services.raid.combat import runs as combat_runs
from gameplay.services.raid.combat import troop_ops
from tests.raid_combat_runs.support import build_attacker_defender


def test_refresh_raid_runs_prefers_async_dispatch(monkeypatch):
    class _Status:
        MARCHING = "marching"
        RETURNING = "returning"
        RETREATED = "retreated"

    class _RaidObjects:
        def __init__(self):
            self._status = None

        def filter(self, **kwargs):
            self._status = kwargs.get("status")
            return self

        def values_list(self, *_args, **_kwargs):
            mapping = {
                _Status.MARCHING: [1, 2],
                _Status.RETURNING: [3],
                _Status.RETREATED: [4],
            }
            return list(mapping.get(self._status, []))

    dummy_cls = type("_RaidRun", (), {"Status": _Status, "objects": _RaidObjects()})
    monkeypatch.setattr(combat_runs, "RaidRun", dummy_cls)

    dispatched = []

    def _dispatch(_task, run_id, stage):
        dispatched.append((run_id, stage))
        return True

    monkeypatch.setattr(combat_runs, "_try_dispatch_raid_refresh_task", _dispatch)

    called = {"battle": 0, "finalize": 0}
    monkeypatch.setattr(
        combat_battle,
        "process_raid_battle",
        lambda *_args, **_kwargs: called.__setitem__("battle", called["battle"] + 1),
    )
    monkeypatch.setattr(
        combat_runs,
        "finalize_raid",
        lambda *_args, **_kwargs: called.__setitem__("finalize", called["finalize"] + 1),
    )

    combat_runs.refresh_raid_runs(SimpleNamespace(id=9), prefer_async=True)

    assert set(dispatched) == {(1, "battle"), (2, "battle"), (3, "return"), (4, "return")}
    assert called == {"battle": 0, "finalize": 0}


def test_refresh_raid_runs_nested_import_error_bubbles_up(monkeypatch):
    class _Status:
        MARCHING = "marching"
        RETURNING = "returning"
        RETREATED = "retreated"

    class _RaidObjects:
        def __init__(self):
            self._status = None

        def filter(self, **kwargs):
            self._status = kwargs.get("status")
            return self

        def values_list(self, *_args, **_kwargs):
            mapping = {
                _Status.MARCHING: [1],
                _Status.RETURNING: [],
                _Status.RETREATED: [],
            }
            return list(mapping.get(self._status, []))

    dummy_cls = type("_RaidRun", (), {"Status": _Status, "objects": _RaidObjects()})
    monkeypatch.setattr(combat_runs, "RaidRun", dummy_cls)

    def _raise_import():
        exc = ModuleNotFoundError("No module named 'redis'")
        exc.name = "redis"
        raise exc

    monkeypatch.setattr(combat_runs, "_import_raid_refresh_tasks", _raise_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        combat_runs.refresh_raid_runs(SimpleNamespace(id=9), prefer_async=True)


@pytest.mark.django_db
def test_collect_due_raid_run_ids_only_returns_due_durable_states(django_user_model):
    attacker, defender = build_attacker_defender(
        django_user_model,
        attacker_username="raid_due_attacker",
        defender_username="raid_due_defender",
    )

    now = timezone.now()
    due_marching = combat_runs.RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=combat_runs.RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=now - timedelta(seconds=1),
    )
    combat_runs.RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=combat_runs.RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=now + timedelta(seconds=60),
    )
    due_returning = combat_runs.RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=combat_runs.RaidRun.Status.RETURNING,
        travel_time=60,
        return_at=now - timedelta(seconds=1),
    )
    due_retreated = combat_runs.RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=combat_runs.RaidRun.Status.RETREATED,
        travel_time=60,
        return_at=now - timedelta(seconds=1),
    )
    combat_runs.RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=combat_runs.RaidRun.Status.RETURNING,
        travel_time=60,
        return_at=now + timedelta(seconds=60),
    )
    combat_runs.RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=combat_runs.RaidRun.Status.COMPLETED,
        travel_time=60,
        battle_at=now - timedelta(seconds=120),
        return_at=now - timedelta(seconds=60),
        completed_at=now - timedelta(seconds=30),
    )

    marching_ids, returning_ids, retreated_ids = combat_runs.collect_due_raid_run_ids(
        attacker,
        now,
        combat_runs.RaidRun,
    )

    assert marching_ids == [due_marching.id]
    assert returning_ids == [due_returning.id]
    assert retreated_ids == [due_retreated.id]


def test_get_active_raids_is_pure_listing_query(monkeypatch):
    manor = SimpleNamespace(id=9)
    persisted = [SimpleNamespace(id=1)]

    monkeypatch.setattr(
        combat_runs,
        "persistence_get_active_raids",
        lambda current_manor, *, raid_run_model: persisted if current_manor is manor else [],
    )

    result = combat_runs.get_active_raids(manor)

    assert result == persisted


def test_prepare_run_for_battle_uses_runs_retreat_wrapper(monkeypatch):
    class _Status:
        RETREATED = "retreated"
        MARCHING = "marching"
        COMPLETED = "completed"

    dummy_raid_run = type("_RaidRun", (), {"Status": _Status})
    monkeypatch.setattr(combat_battle, "RaidRun", dummy_raid_run)

    called = {}

    def _finalize_retreat(run, **kwargs):
        called["run"] = run
        called["kwargs"] = kwargs

    monkeypatch.setattr(combat_runs, "_finalize_raid_retreat", _finalize_retreat)
    monkeypatch.setattr(combat_runs, "_add_troops_batch", lambda *_args, **_kwargs: None)

    locked_run = SimpleNamespace(
        status=_Status.RETREATED,
        return_at=timezone.now() - timedelta(seconds=1),
    )
    monkeypatch.setattr(combat_battle, "_load_locked_raid_run", lambda _run_pk: locked_run)

    assert combat_battle._prepare_run_for_battle(run_pk=1, now=timezone.now()) is None
    assert called["run"] is locked_run
    assert set(called["kwargs"]) == {"now"}


def test_bulk_create_troops_with_fallback_upserts_without_losing_counts(monkeypatch):
    update_sequences = {
        "existing": [1],
        "missing": [0],
        "race": [0, 1],
    }
    update_calls = []
    create_calls = []

    class _QS:
        def __init__(self, key):
            self.key = key

        def update(self, **kwargs):
            update_calls.append((self.key, kwargs))
            seq = update_sequences.get(self.key, [])
            if seq:
                return seq.pop(0)
            return 0

    class _Objects:
        @staticmethod
        def filter(*, manor, troop_template):
            return _QS(troop_template.key)

        @staticmethod
        def create(*, manor, troop_template, count):
            create_calls.append((troop_template.key, count))
            if troop_template.key == "race":
                raise IntegrityError("duplicate key")
            return SimpleNamespace(manor=manor, troop_template=troop_template, count=count)

    monkeypatch.setattr(troop_ops, "PlayerTroop", type("_PlayerTroop", (), {"objects": _Objects()}))

    to_create = [
        SimpleNamespace(manor="m", troop_template=SimpleNamespace(key="existing"), count=2),
        SimpleNamespace(manor="m", troop_template=SimpleNamespace(key="missing"), count=3),
        SimpleNamespace(manor="m", troop_template=SimpleNamespace(key="race"), count=4),
    ]
    combat_runs._bulk_create_troops_with_fallback(to_create, now="now")

    assert create_calls == [("missing", 3), ("race", 4)]
    assert [key for key, _kwargs in update_calls] == ["existing", "missing", "race", "race"]
