from __future__ import annotations

import contextlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from battle.models import TroopTemplate
from core.exceptions import MessageError, ScoutStartError
from gameplay.constants import PVPConstants
from gameplay.models import PlayerTroop, ScoutRecord
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid import activity_refresh as raid_activity_refresh
from gameplay.services.raid import scout as scout_service
from gameplay.services.raid import scout_refresh as scout_refresh_command


def test_refresh_scout_records_command_skips_finalize_when_nothing_due():
    calls = {"dispatch": 0, "finalize": 0}

    scout_refresh_command.refresh_scout_records_command(
        SimpleNamespace(id=7),
        prefer_async=True,
        now_fn=lambda: timezone.now(),
        collect_due_ids_fn=lambda _manor, _now: ([], []),
        dispatch_async_fn=lambda *_args: calls.__setitem__("dispatch", calls["dispatch"] + 1) or ([], [], True),
        finalize_due_fn=lambda *_args: calls.__setitem__("finalize", calls["finalize"] + 1),
    )

    assert calls == {"dispatch": 0, "finalize": 0}


def test_refresh_raid_activity_delegates_explicit_refresh_commands():
    calls: list[tuple[object, ...]] = []
    manor = SimpleNamespace(id=7)

    raid_activity_refresh.refresh_raid_activity(
        manor,
        prefer_async=True,
        refresh_scout_records_func=lambda current_manor, *, prefer_async=False: calls.append(
            ("scout", current_manor, prefer_async)
        ),
        refresh_raid_runs_func=lambda current_manor, *, prefer_async=False: calls.append(
            ("raid", current_manor, prefer_async)
        ),
    )

    assert calls == [
        ("scout", manor, True),
        ("raid", manor, True),
    ]


def test_refresh_scout_records_command_skips_sync_finalize_when_async_dispatch_finishes():
    calls = {"dispatch": 0, "finalize": 0}

    scout_refresh_command.refresh_scout_records_command(
        SimpleNamespace(id=8),
        prefer_async=True,
        now_fn=lambda: timezone.now(),
        collect_due_ids_fn=lambda _manor, _now: ([11], [12]),
        dispatch_async_fn=lambda *_args: calls.__setitem__("dispatch", calls["dispatch"] + 1) or ([], [], True),
        finalize_due_fn=lambda *_args: calls.__setitem__("finalize", calls["finalize"] + 1),
    )

    assert calls == {"dispatch": 1, "finalize": 0}


@pytest.mark.django_db
def test_collect_due_scout_record_ids_only_returns_due_durable_states(django_user_model):
    attacker = ensure_manor(django_user_model.objects.create_user(username="scout_due_attacker", password="pass123"))
    defender = ensure_manor(django_user_model.objects.create_user(username="scout_due_defender", password="pass123"))

    now = timezone.now()
    due_outbound = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        complete_at=now - timedelta(seconds=1),
    )
    ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        complete_at=now + timedelta(seconds=60),
    )
    due_return = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.RETURNING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        return_at=now - timedelta(seconds=1),
        complete_at=now - timedelta(seconds=120),
    )
    ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.RETURNING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        return_at=now + timedelta(seconds=60),
        complete_at=now - timedelta(seconds=120),
    )
    ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SUCCESS,
        scout_cost=1,
        success_rate=1.0,
        travel_time=60,
        complete_at=now - timedelta(seconds=120),
        return_at=now - timedelta(seconds=60),
        completed_at=now - timedelta(seconds=30),
        is_success=True,
        intel_data={},
    )

    scouting_ids, returning_ids = scout_refresh_command.collect_due_scout_record_ids(attacker, now)

    assert scouting_ids == [due_outbound.id]
    assert returning_ids == [due_return.id]


def test_refresh_scout_records_prefers_async_dispatch(monkeypatch):
    class _Status:
        SCOUTING = "scouting"
        RETURNING = "returning"

    class _ScoutObjects:
        def __init__(self):
            self._status = None

        def filter(self, **kwargs):
            self._status = kwargs.get("status")
            return self

        def values_list(self, *_args, **_kwargs):
            mapping = {
                _Status.SCOUTING: [11, 12],
                _Status.RETURNING: [13],
            }
            return list(mapping.get(self._status, []))

    dummy_cls = type("_ScoutRecord", (), {"Status": _Status, "objects": _ScoutObjects()})
    monkeypatch.setattr(scout_service, "ScoutRecord", dummy_cls)

    dispatched = []

    def _dispatch(_task, record_id, phase):
        dispatched.append((record_id, phase))
        return True

    monkeypatch.setattr(
        scout_refresh_command,
        "try_dispatch_scout_refresh_task",
        lambda task, record_id, phase, *, logger: _dispatch(task, record_id, phase),
    )

    called = {"scout": 0, "return": 0}
    monkeypatch.setattr(
        scout_service,
        "finalize_scout",
        lambda *_args, **_kwargs: called.__setitem__("scout", called["scout"] + 1),
    )
    monkeypatch.setattr(
        scout_service,
        "finalize_scout_return",
        lambda *_args, **_kwargs: called.__setitem__("return", called["return"] + 1),
    )

    scout_service.refresh_scout_records(SimpleNamespace(id=7), prefer_async=True)

    assert set(dispatched) == {(11, "outbound"), (12, "outbound"), (13, "return")}
    assert called == {"scout": 0, "return": 0}


def test_refresh_scout_records_falls_back_to_sync_when_task_import_fails(monkeypatch):
    class _Status:
        SCOUTING = "scouting"
        RETURNING = "returning"

    class _ScoutObjects:
        def __init__(self):
            self._status = None

        def filter(self, **kwargs):
            self._status = kwargs.get("status")
            return self

        def values_list(self, *_args, **_kwargs):
            mapping = {
                _Status.SCOUTING: [21],
                _Status.RETURNING: [22],
            }
            return list(mapping.get(self._status, []))

    dummy_cls = type("_ScoutRecord", (), {"Status": _Status, "objects": _ScoutObjects()})
    monkeypatch.setattr(scout_service, "ScoutRecord", dummy_cls)
    monkeypatch.setattr(scout_refresh_command, "resolve_scout_refresh_tasks", lambda **_kwargs: None)

    called = {"scout": 0, "return": 0}
    monkeypatch.setattr(
        scout_refresh_command,
        "finalize_due_scout_records",
        lambda _now, scouting_ids, returning_ids, **_kwargs: called.update(
            {"scout": len(scouting_ids), "return": len(returning_ids)}
        ),
    )

    scout_service.refresh_scout_records(SimpleNamespace(id=7), prefer_async=True)

    assert called == {"scout": 1, "return": 1}


def test_resolve_scout_refresh_tasks_nested_import_error_bubbles_up(monkeypatch):
    def _raise_import(_task_name):
        exc = ModuleNotFoundError("No module named 'redis'")
        exc.name = "redis"
        raise exc

    monkeypatch.setattr(scout_refresh_command, "resolve_scout_task", _raise_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        scout_refresh_command.resolve_scout_refresh_tasks(logger=scout_service.logger)


def test_resolve_scout_refresh_tasks_missing_target_module_falls_back_to_none(monkeypatch):
    def _raise_import(_task_name):
        exc = ModuleNotFoundError("No module named 'gameplay.tasks.pvp'")
        exc.name = "gameplay.tasks.pvp"
        raise exc

    monkeypatch.setattr(scout_refresh_command, "resolve_scout_task", _raise_import)

    assert scout_refresh_command.resolve_scout_refresh_tasks(logger=scout_service.logger) is None


def test_resolve_scout_refresh_tasks_programming_error_bubbles_up(monkeypatch):
    monkeypatch.setattr(
        scout_refresh_command,
        "resolve_scout_task",
        lambda _task_name: (_ for _ in ()).throw(AssertionError("broken scout refresh import contract")),
    )

    with pytest.raises(AssertionError, match="broken scout refresh import contract"):
        scout_refresh_command.resolve_scout_refresh_tasks(logger=scout_service.logger)


def test_send_scout_success_message_tolerates_invalid_intel_shape(monkeypatch):
    sent = {}

    def _create_message(*, manor, kind, title, body):
        sent.update({"manor": manor, "kind": kind, "title": title, "body": body})

    monkeypatch.setattr(scout_service.scout_followups, "create_message", _create_message)

    record = SimpleNamespace(
        intel_data=["bad-shape"],
        attacker=SimpleNamespace(id=1),
        defender=SimpleNamespace(display_name="目标庄园"),
    )

    scout_service.scout_followups.send_scout_success_message(record)

    assert sent["manor"].id == 1
    assert sent["kind"] == "system"
    assert "侦察报告" in sent["title"]
    assert "未知" in sent["body"]


def test_start_scout_rechecks_attack_constraints_inside_transaction(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1)
    defender = SimpleNamespace(pk=2, id=2)
    calls = {"can_attack": 0}

    def _fake_can_attack(*_args, **_kwargs):
        calls["can_attack"] += 1
        if calls["can_attack"] == 1:
            return True, ""
        return False, "对方处于免战牌保护期"

    monkeypatch.setattr(scout_service.scout_start_command.transaction, "atomic", contextlib.nullcontext)
    monkeypatch.setattr(scout_service, "can_attack_target", _fake_can_attack)
    monkeypatch.setattr(scout_service, "check_scout_cooldown", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(scout_service, "get_scout_count", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(scout_service, "_lock_manor_pair", lambda *_args, **_kwargs: (attacker, defender))

    with pytest.raises(ScoutStartError, match="免战牌保护期"):
        scout_service.start_scout(attacker, defender)

    assert calls["can_attack"] == 2


def test_start_scout_precheck_uses_uncached_attack_check(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1)
    defender = SimpleNamespace(pk=2, id=2)
    seen = {"use_cached_recent_attacks": None, "check_defeat_protection": None}

    def _fake_can_attack(*_args, **kwargs):
        seen["use_cached_recent_attacks"] = kwargs.get("use_cached_recent_attacks")
        seen["check_defeat_protection"] = kwargs.get("check_defeat_protection")
        return False, "blocked"

    monkeypatch.setattr(scout_service, "can_attack_target", _fake_can_attack)

    with pytest.raises(ScoutStartError, match="blocked"):
        scout_service.start_scout(attacker, defender)

    assert seen["use_cached_recent_attacks"] is False
    assert seen["check_defeat_protection"] is False


def test_lock_manor_pair_raises_scout_start_error_when_target_missing(monkeypatch):
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
    monkeypatch.setattr(scout_service, "Manor", dummy_manor_model)

    with pytest.raises(ScoutStartError, match="目标庄园不存在"):
        scout_service._lock_manor_pair(1, 2)


@pytest.mark.django_db(transaction=True)
def test_finalize_scout_return_marks_retreated_records_without_failure_message(django_user_model, monkeypatch):
    attacker = ensure_manor(
        django_user_model.objects.create_user(username="scout_retreat_attacker", password="pass123")
    )
    defender = ensure_manor(
        django_user_model.objects.create_user(username="scout_retreat_defender", password="pass123")
    )
    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 3},
    )

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        complete_at=timezone.now() + timedelta(seconds=60),
    )

    request_time = timezone.now()
    monkeypatch.setattr(scout_service.timezone, "now", lambda: request_time)
    monkeypatch.setattr(scout_service.scout_followups, "safe_apply_async", lambda *_args, **_kwargs: True)

    scout_service.request_scout_retreat(record)

    record.refresh_from_db()
    troop.refresh_from_db()
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.was_retreated is True
    assert record.is_success is None
    assert troop.count == 4

    sent = {"retreat": 0, "fail": 0}
    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_retreat_message",
        lambda *_args, **_kwargs: sent.__setitem__("retreat", sent["retreat"] + 1),
    )
    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_fail_message",
        lambda *_args, **_kwargs: sent.__setitem__("fail", sent["fail"] + 1),
    )
    callbacks = []
    monkeypatch.setattr(
        scout_service.scout_followups.transaction, "on_commit", lambda callback: callbacks.append(callback)
    )

    complete_time = request_time + timedelta(seconds=5)
    scout_service.finalize_scout_return(record, now=complete_time)

    record.refresh_from_db()
    troop.refresh_from_db()
    assert record.status == ScoutRecord.Status.FAILED
    assert record.was_retreated is True
    assert record.completed_at == complete_time
    assert troop.count == 4
    assert len(callbacks) == 1
    assert sent == {"retreat": 0, "fail": 0}

    callbacks[0]()

    assert sent == {"retreat": 1, "fail": 0}


@pytest.mark.django_db(transaction=True)
def test_request_scout_retreat_recreates_missing_scout_troop_row(django_user_model, monkeypatch):
    attacker = ensure_manor(
        django_user_model.objects.create_user(username="scout_retreat_restore_attacker", password="pass123")
    )
    defender = ensure_manor(
        django_user_model.objects.create_user(username="scout_retreat_restore_defender", password="pass123")
    )
    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    PlayerTroop.objects.filter(manor=attacker, troop_template=scout_template).delete()

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=2,
        success_rate=0.5,
        travel_time=60,
        complete_at=timezone.now() + timedelta(seconds=60),
    )

    request_time = timezone.now()
    monkeypatch.setattr(scout_service.timezone, "now", lambda: request_time)
    monkeypatch.setattr(scout_service.scout_followups, "safe_apply_async", lambda *_args, **_kwargs: True)

    scout_service.request_scout_retreat(record)

    record.refresh_from_db()
    troop = PlayerTroop.objects.get(manor=attacker, troop_template=scout_template)
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.was_retreated is True
    assert troop.count == 2


@pytest.mark.django_db(transaction=True)
def test_finalize_scout_return_recreates_missing_scout_troop_row_for_success(django_user_model, monkeypatch):
    attacker = ensure_manor(
        django_user_model.objects.create_user(username="scout_success_restore_attacker", password="pass123")
    )
    defender = ensure_manor(
        django_user_model.objects.create_user(username="scout_success_restore_defender", password="pass123")
    )
    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    PlayerTroop.objects.filter(manor=attacker, troop_template=scout_template).delete()

    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.RETURNING,
        scout_cost=3,
        success_rate=1.0,
        return_at=timezone.now() + timedelta(seconds=30),
        complete_at=timezone.now() - timedelta(seconds=30),
        travel_time=30,
        is_success=True,
        intel_data={"troop_description": "少量", "guest_count": 1, "avg_guest_level": 1, "asset_level": "普通"},
    )

    callbacks = []
    monkeypatch.setattr(
        scout_service.scout_followups.transaction, "on_commit", lambda callback: callbacks.append(callback)
    )
    monkeypatch.setattr(scout_service.scout_followups, "send_scout_success_message", lambda *_args, **_kwargs: None)

    complete_time = timezone.now()
    scout_service.finalize_scout_return(record, now=complete_time)

    record.refresh_from_db()
    troop = PlayerTroop.objects.get(manor=attacker, troop_template=scout_template)
    assert record.status == ScoutRecord.Status.SUCCESS
    assert record.completed_at == complete_time
    assert troop.count == 3
    assert len(callbacks) == 1


@pytest.mark.django_db(transaction=True)
def test_finalize_scout_detected_message_runs_after_commit_and_failure_does_not_rollback(
    django_user_model, monkeypatch
):
    attacker = ensure_manor(django_user_model.objects.create_user(username="scout_detect_attacker", password="pass123"))
    defender = ensure_manor(django_user_model.objects.create_user(username="scout_detect_defender", password="pass123"))
    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=0.0,
        travel_time=45,
        complete_at=timezone.now() + timedelta(seconds=45),
    )

    monkeypatch.setattr(scout_service, "_roll_scout_success", lambda: 0.5)
    dispatched = []
    monkeypatch.setattr(
        scout_service.scout_followups.scout_refresh_command,
        "resolve_scout_task",
        lambda task_name: SimpleNamespace(name=task_name),
    )
    monkeypatch.setattr(
        scout_service.scout_followups,
        "safe_apply_async",
        lambda task, *, args, countdown, **_kwargs: dispatched.append(
            {
                "task_name": getattr(task, "name", str(task)),
                "args": args,
                "countdown": countdown,
            }
        )
        or True,
    )

    sent = {"count": 0}

    def _fail_detected(*_args, **_kwargs):
        sent["count"] += 1
        raise MessageError("message backend down")

    monkeypatch.setattr(scout_service.scout_followups, "send_scout_detected_message", _fail_detected)
    callbacks = []
    monkeypatch.setattr(
        scout_service.scout_followups.transaction, "on_commit", lambda callback: callbacks.append(callback)
    )

    now = timezone.now()
    scout_service.finalize_scout(record, now=now)

    record.refresh_from_db()
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.is_success is False
    assert record.return_at == now + timedelta(seconds=record.travel_time)
    assert sent["count"] == 0
    assert dispatched == []
    assert len(callbacks) == 2

    for callback in callbacks:
        callback()

    record.refresh_from_db()
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.is_success is False
    assert sent["count"] == 1
    assert dispatched == [
        {
            "task_name": "complete_scout_return_task",
            "args": [record.id],
            "countdown": record.travel_time,
        }
    ]


def test_run_scout_followup_programming_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(
        attacker=SimpleNamespace(display_name="进攻方", location_display="A-1"),
        defender=SimpleNamespace(display_name="防守方"),
    )

    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_detected_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken scout message contract")),
    )

    with pytest.raises(AssertionError, match="broken scout message contract"):
        scout_service.scout_followups.run_scout_followup("detected_message", record)


def test_run_scout_followup_runtime_marker_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(
        attacker=SimpleNamespace(display_name="进攻方", location_display="A-1"),
        defender=SimpleNamespace(display_name="防守方"),
    )

    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_detected_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        scout_service.scout_followups.run_scout_followup("detected_message", record)


@pytest.mark.django_db(transaction=True)
def test_start_scout_dispatch_runs_after_commit(django_user_model, monkeypatch):
    attacker = ensure_manor(django_user_model.objects.create_user(username="scout_start_attacker", password="pass123"))
    defender = ensure_manor(django_user_model.objects.create_user(username="scout_start_defender", password="pass123"))
    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 2},
    )

    callbacks = []
    monkeypatch.setattr(
        scout_service.scout_followups.transaction, "on_commit", lambda callback: callbacks.append(callback)
    )
    monkeypatch.setattr(scout_service, "can_attack_target", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(scout_service, "calculate_scout_success_rate", lambda *_args, **_kwargs: 0.5)
    monkeypatch.setattr(scout_service, "calculate_scout_travel_time", lambda *_args, **_kwargs: 45)
    monkeypatch.setattr(
        scout_service.scout_followups.scout_refresh_command,
        "resolve_scout_task",
        lambda task_name: SimpleNamespace(name=task_name),
    )

    dispatched = []
    monkeypatch.setattr(
        scout_service.scout_followups,
        "safe_apply_async",
        lambda task, *, args, countdown, **_kwargs: dispatched.append(
            {
                "task_name": getattr(task, "name", str(task)),
                "args": args,
                "countdown": countdown,
            }
        )
        or True,
    )

    record = scout_service.start_scout(attacker, defender)

    troop.refresh_from_db()
    record.refresh_from_db()
    assert troop.count == 1
    assert record.status == ScoutRecord.Status.SCOUTING
    assert len(callbacks) == 1
    assert dispatched == []

    callbacks[0]()

    assert dispatched == [
        {
            "task_name": "complete_scout_task",
            "args": [record.id],
            "countdown": 45,
        }
    ]


def test_dispatch_scout_task_nested_import_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(id=17, attacker_id=3, defender_id=5)

    def _raise_import(_task_name):
        exc = ModuleNotFoundError("No module named 'redis'")
        exc.name = "redis"
        raise exc

    monkeypatch.setattr(scout_service.scout_followups.scout_refresh_command, "resolve_scout_task", _raise_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        scout_service.scout_followups.dispatch_scout_task(
            "complete_scout_task",
            countdown=30,
            record=record,
            log_message="complete_scout_task dispatch failed",
            false_log_message="complete_scout_task dispatch returned False; scout may remain in outbound state",
        )


def test_dispatch_scout_task_missing_target_module_degrades(monkeypatch):
    record = SimpleNamespace(id=18, attacker_id=3, defender_id=5)

    def _raise_import(_task_name):
        exc = ModuleNotFoundError("No module named 'gameplay.tasks.pvp'")
        exc.name = "gameplay.tasks.pvp"
        raise exc

    monkeypatch.setattr(scout_service.scout_followups.scout_refresh_command, "resolve_scout_task", _raise_import)

    scout_service.scout_followups.dispatch_scout_task(
        "complete_scout_task",
        countdown=30,
        record=record,
        log_message="complete_scout_task dispatch failed",
        false_log_message="complete_scout_task dispatch returned False; scout may remain in outbound state",
    )


def test_dispatch_scout_task_programming_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(id=19, attacker_id=3, defender_id=5)

    monkeypatch.setattr(
        scout_service.scout_followups.scout_refresh_command,
        "resolve_scout_task",
        lambda _task_name: (_ for _ in ()).throw(AssertionError("broken scout task import contract")),
    )

    with pytest.raises(AssertionError, match="broken scout task import contract"):
        scout_service.scout_followups.dispatch_scout_task(
            "complete_scout_task",
            countdown=30,
            record=record,
            log_message="complete_scout_task dispatch failed",
            false_log_message="complete_scout_task dispatch returned False; scout may remain in outbound state",
        )
