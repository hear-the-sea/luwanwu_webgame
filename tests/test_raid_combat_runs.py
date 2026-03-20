from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.exceptions import RaidStartError
from gameplay.services.raid import utils as raid_utils
from gameplay.services.raid.combat import battle as combat_battle
from gameplay.services.raid.combat import runs as combat_runs
from gameplay.services.raid.combat import troop_ops


def test_send_raid_incoming_message_builds_body(monkeypatch):
    sent = {}

    def _create_message(*, manor, kind, title, body):
        sent.update({"manor": manor, "kind": kind, "title": title, "body": body})

    monkeypatch.setattr(combat_runs, "create_message", _create_message)

    run = SimpleNamespace(
        attacker=SimpleNamespace(location_display="江南", display_name="张三"),
        defender=SimpleNamespace(id=2),
        battle_at=datetime(2026, 2, 7, 12, 0, tzinfo=dt_timezone.utc),
    )

    combat_runs._send_raid_incoming_message(run)

    assert sent["manor"].id == 2
    assert sent["kind"] == "system"
    assert "敌军来袭" in sent["title"]
    assert "江南" in sent["body"]
    assert "张三" in sent["body"]


def test_can_raid_retreat_requires_marching(monkeypatch):
    class _Status:
        MARCHING = "marching"

    monkeypatch.setattr(combat_runs, "RaidRun", type("_RaidRun", (), {"Status": _Status}))

    run = SimpleNamespace(status="other", is_retreating=False)
    assert combat_runs.can_raid_retreat(run) is False

    run.status = _Status.MARCHING
    assert combat_runs.can_raid_retreat(run) is True

    run.is_retreating = True
    assert combat_runs.can_raid_retreat(run) is False


def test_return_surviving_troops_returns_all_when_no_report(monkeypatch):
    called = {}

    def _add_batch(_manor, payload):
        called["payload"] = payload

    monkeypatch.setattr(troop_ops, "_add_troops_batch", _add_batch)

    run = SimpleNamespace(attacker=object(), troop_loadout={"inf": 5}, battle_report=None)
    combat_runs._return_surviving_troops(run)

    assert called["payload"] == {"inf": 5}


def test_return_surviving_troops_filters_casualties(monkeypatch):
    monkeypatch.setattr("battle.troops.load_troop_templates", lambda: {"inf": {"label": "步兵"}})

    called = {}

    def _add_batch(_manor, payload):
        called["payload"] = payload

    monkeypatch.setattr(troop_ops, "_add_troops_batch", _add_batch)

    report = SimpleNamespace(
        losses={
            "attacker": {
                "casualties": [
                    {"key": "inf", "lost": 2},
                    {"key": "unknown", "lost": 99},
                    {"key": "inf", "lost": "bad"},
                ]
            }
        }
    )
    run = SimpleNamespace(attacker=object(), troop_loadout={"inf": 5}, battle_report=report)

    combat_runs._return_surviving_troops(run)

    assert called["payload"] == {"inf": 3}


def test_extract_raid_troops_lost_handles_non_mapping_losses(monkeypatch):
    monkeypatch.setattr("battle.troops.load_troop_templates", lambda: {"inf": {"label": "步兵"}})

    report = SimpleNamespace(losses=["not-a-mapping"])
    assert troop_ops._extract_raid_troops_lost({"inf": 3}, report) == {}


def test_return_surviving_troops_ignores_invalid_loadout_shape(monkeypatch):
    called = {"count": 0}

    def _add_batch(_manor, payload):
        called["count"] += 1
        called["payload"] = payload

    monkeypatch.setattr(troop_ops, "_add_troops_batch", _add_batch)

    run = SimpleNamespace(attacker=object(), troop_loadout=["bad-shape"], battle_report=None)
    combat_runs._return_surviving_troops(run)

    assert called["count"] == 0


def test_deduct_troops_raises_when_missing(monkeypatch):
    class _PlayerTroop:
        objects = SimpleNamespace(
            select_for_update=lambda: SimpleNamespace(
                filter=lambda **_kwargs: SimpleNamespace(select_related=lambda *_a, **_k: [])
            )
        )

    monkeypatch.setattr(troop_ops, "PlayerTroop", _PlayerTroop)

    with pytest.raises(RaidStartError, match="没有该类型的护院"):
        combat_runs._deduct_troops(SimpleNamespace(), {"inf": 1})


def test_normalize_and_validate_raid_loadout_translates_battle_value_error(monkeypatch):
    monkeypatch.setattr(
        "battle.combatants_pkg.normalize_troop_loadout",
        lambda troop_loadout, default_if_empty=False: troop_loadout,
    )
    monkeypatch.setattr(
        "battle.services.validate_troop_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("门客容量不足")),
    )

    with pytest.raises(RaidStartError, match="门客容量不足"):
        combat_runs._normalize_and_validate_raid_loadout([], {"inf": 1})


def test_lock_manor_pair_raises_raid_start_error_when_target_missing():
    class _Objects:
        @staticmethod
        def select_for_update():
            return _Objects()

        @staticmethod
        def filter(**_kwargs):
            return _Objects()

        @staticmethod
        def order_by(*_args, **_kwargs):
            return []

    dummy_manor_model = type("_Manor", (), {"objects": _Objects()})

    with pytest.raises(RaidStartError, match="目标庄园不存在"):
        combat_runs.persistence_lock_manor_pair(1, 2, manor_model=dummy_manor_model)


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


def test_start_raid_rechecks_attack_constraints_inside_transaction(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1, defeat_protection_until=None)
    defender = SimpleNamespace(pk=2, id=2)

    monkeypatch.setattr(combat_runs.transaction, "atomic", contextlib.nullcontext)
    monkeypatch.setattr(
        combat_runs,
        "_validate_and_normalize_raid_inputs",
        lambda *_args, **_kwargs: ([101], {"inf": 1}),
    )
    monkeypatch.setattr(combat_runs, "_lock_manor_pair", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(
        combat_runs,
        "_recheck_can_attack_target",
        lambda *_args, **_kwargs: (False, "对方处于免战牌保护期"),
    )

    def _unexpected_active_count(*_args, **_kwargs):
        raise AssertionError("should not read active raid count when lock-time attack check fails")

    called = {"load_guests": 0}

    def _unexpected_load_guests(*_args, **_kwargs):
        called["load_guests"] += 1
        return []

    monkeypatch.setattr(combat_runs, "get_active_raid_count", _unexpected_active_count)
    monkeypatch.setattr(combat_runs, "_load_and_validate_attacker_guests", _unexpected_load_guests)

    with pytest.raises(RaidStartError, match="免战牌保护期"):
        combat_runs.start_raid(attacker, defender, [101], {"inf": 1})

    assert called["load_guests"] == 0


@pytest.mark.django_db(transaction=True)
def test_start_raid_invalidates_recent_attack_cache_on_commit(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1, defeat_protection_until=None)
    defender = SimpleNamespace(pk=2, id=2)
    invalidated = {"defender_id": None}

    monkeypatch.setattr(
        combat_runs,
        "_validate_and_normalize_raid_inputs",
        lambda *_args, **_kwargs: ([101], {"inf": 1}),
    )
    monkeypatch.setattr(combat_runs, "_lock_manor_pair", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_runs, "_recheck_can_attack_target", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(combat_runs, "get_active_raid_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(combat_runs, "_load_and_validate_attacker_guests", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(combat_runs, "_normalize_and_validate_raid_loadout", lambda *_args, **_kwargs: {"inf": 1})
    monkeypatch.setattr(combat_runs, "_deduct_troops", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "calculate_raid_travel_time", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        combat_runs,
        "_create_raid_run_record",
        lambda *_args, **_kwargs: SimpleNamespace(id=99, attacker=attacker, defender=defender),
    )
    monkeypatch.setattr(combat_runs, "_send_raid_incoming_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "_dispatch_raid_battle_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "gameplay.services.raid.utils.invalidate_recent_attacks_cache",
        lambda defender_id: invalidated.__setitem__("defender_id", defender_id),
    )

    with transaction.atomic():
        with TestCase.captureOnCommitCallbacks(execute=False) as callbacks:
            combat_runs.start_raid(attacker, defender, [101], {"inf": 1})

        assert invalidated["defender_id"] is None
        assert len(callbacks) == 1

        callbacks[0]()

    assert invalidated["defender_id"] == defender.id


@pytest.mark.django_db(transaction=True)
def test_start_raid_clears_attacker_defeat_protection_on_success(monkeypatch):
    now = timezone.now()
    saved = {"fields": None}
    attacker = SimpleNamespace(
        pk=1,
        id=1,
        defeat_protection_until=now + timedelta(minutes=15),
        save=lambda *, update_fields: saved.__setitem__("fields", update_fields),
    )
    defender = SimpleNamespace(pk=2, id=2)

    monkeypatch.setattr(
        combat_runs,
        "_validate_and_normalize_raid_inputs",
        lambda *_args, **_kwargs: ([101], {"inf": 1}),
    )
    monkeypatch.setattr(combat_runs, "_lock_manor_pair", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_runs, "_recheck_can_attack_target", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(combat_runs, "get_active_raid_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(combat_runs, "_load_and_validate_attacker_guests", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(combat_runs, "_normalize_and_validate_raid_loadout", lambda *_args, **_kwargs: {"inf": 1})
    monkeypatch.setattr(combat_runs, "_deduct_troops", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "calculate_raid_travel_time", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        combat_runs,
        "_create_raid_run_record",
        lambda *_args, **_kwargs: SimpleNamespace(id=99, attacker=attacker, defender=defender),
    )
    monkeypatch.setattr(combat_runs, "_send_raid_incoming_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "_dispatch_raid_battle_task", lambda *_args, **_kwargs: None)

    with transaction.atomic():
        with TestCase.captureOnCommitCallbacks(execute=True) as callbacks:
            combat_runs.start_raid(attacker, defender, [101], {"inf": 1})

        assert len(callbacks) == 1

    assert attacker.defeat_protection_until is None
    assert saved["fields"] == ["defeat_protection_until"]


def test_start_raid_succeeds_when_incoming_message_fails(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1, defeat_protection_until=None)
    defender = SimpleNamespace(pk=2, id=2)
    created_run = SimpleNamespace(id=99, attacker=attacker, defender=defender)
    dispatched = {"run_id": None, "travel_time": None}

    monkeypatch.setattr(combat_runs.transaction, "atomic", contextlib.nullcontext)
    monkeypatch.setattr(
        combat_runs,
        "_validate_and_normalize_raid_inputs",
        lambda *_args, **_kwargs: ([101], {"inf": 1}),
    )
    monkeypatch.setattr(combat_runs, "_lock_manor_pair", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_runs, "_recheck_can_attack_target", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(combat_runs, "get_active_raid_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(combat_runs, "_load_and_validate_attacker_guests", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(combat_runs, "_normalize_and_validate_raid_loadout", lambda *_args, **_kwargs: {"inf": 1})
    monkeypatch.setattr(combat_runs, "_deduct_troops", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_runs, "calculate_raid_travel_time", lambda *_args, **_kwargs: 45)
    monkeypatch.setattr(combat_runs, "_create_raid_run_record", lambda *_args, **_kwargs: created_run)
    monkeypatch.setattr(combat_runs, "_invalidate_recent_attacks_cache_on_commit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        combat_runs,
        "_send_raid_incoming_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message down")),
    )
    monkeypatch.setattr(
        combat_runs,
        "_dispatch_raid_battle_task",
        lambda run, travel_time: dispatched.update({"run_id": run.id, "travel_time": travel_time}),
    )

    result = combat_runs.start_raid(attacker, defender, [101], {"inf": 1})

    assert result is created_run
    assert dispatched == {"run_id": 99, "travel_time": 45}


def test_dispatch_raid_battle_task_processes_sync_when_due_dispatch_fails(monkeypatch):
    processed: list[int] = []

    import gameplay.tasks as gameplay_tasks

    monkeypatch.setattr(gameplay_tasks, "process_raid_battle_task", object(), raising=False)
    monkeypatch.setattr(combat_runs, "safe_apply_async", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(combat_battle, "process_raid_battle", lambda run, **_kwargs: processed.append(run.id))

    combat_runs._dispatch_raid_battle_task(SimpleNamespace(id=123), travel_time=0)

    assert processed == [123]


def test_validate_and_normalize_raid_inputs_uses_uncached_attack_check(monkeypatch):
    attacker = SimpleNamespace(id=1)
    defender = SimpleNamespace(id=2)
    seen = {"use_cached_recent_attacks": None}

    def _fake_can_attack(_attacker, _defender, **kwargs):
        seen["use_cached_recent_attacks"] = kwargs.get("use_cached_recent_attacks")
        return True, ""

    monkeypatch.setattr(raid_utils, "can_attack_target", _fake_can_attack)
    monkeypatch.setattr(combat_runs, "get_active_raid_count", lambda *_args, **_kwargs: 0)

    guest_ids, troop_loadout = combat_runs._validate_and_normalize_raid_inputs(
        attacker,
        defender,
        [101],
        {"inf": 1},
    )

    assert guest_ids == [101]
    assert troop_loadout == {"inf": 1}
    assert seen["use_cached_recent_attacks"] is False
