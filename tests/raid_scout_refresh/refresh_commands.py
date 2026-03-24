from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from gameplay.models import ScoutRecord
from gameplay.services.raid import activity_refresh as raid_activity_refresh
from gameplay.services.raid import scout as scout_service
from gameplay.services.raid import scout_refresh as scout_refresh_command
from tests.raid_scout_refresh.support import build_attacker_defender


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
    attacker, defender = build_attacker_defender(
        django_user_model,
        attacker_username="scout_due_attacker",
        defender_username="scout_due_defender",
    )

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
