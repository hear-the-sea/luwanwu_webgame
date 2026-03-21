from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest
from django.utils import timezone

import gameplay.services.missions_impl.execution as mission_execution
import gameplay.services.missions_impl.launch_post_actions as mission_launch_post_actions
from core.exceptions import MessageError


class _DueRunsManager:
    def __init__(self, ids):
        self.ids = ids

    def filter(self, **_kwargs):
        return self

    def values_list(self, *_args, **_kwargs):
        return list(self.ids)


class _RunObjects:
    def __init__(self, runs):
        self._runs = list(runs)
        self._selected = list(runs)

    def select_related(self, *_args, **_kwargs):
        return self

    def prefetch_related(self, *_args, **_kwargs):
        return self

    def filter(self, **kwargs):
        selected_ids = kwargs.get("id__in")
        if selected_ids is None:
            self._selected = list(self._runs)
        else:
            selected_set = set(selected_ids)
            self._selected = [run for run in self._runs if run.id in selected_set]
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self._selected)


def test_refresh_mission_runs_uses_sync_for_small_backlog(monkeypatch):
    class _Status:
        ACTIVE = "active"

    runs = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    mission_run_cls = type("_MissionRun", (), {"Status": _Status, "objects": _RunObjects(runs)})

    monkeypatch.setattr(mission_execution, "MissionRun", mission_run_cls)
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 3, raising=False)

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "try_dispatch_mission_refresh_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not dispatch async")),
    )

    manor = SimpleNamespace(mission_runs=_DueRunsManager(ids=[1, 2]))

    mission_execution.refresh_mission_runs(manor)

    assert finalized == [1, 2]


def test_refresh_mission_runs_dispatches_async_for_large_backlog(monkeypatch):
    class _Status:
        ACTIVE = "active"

    mission_run_cls = type("_MissionRun", (), {"Status": _Status, "objects": _RunObjects([])})

    monkeypatch.setattr(mission_execution, "MissionRun", mission_run_cls)
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 2, raising=False)

    dispatched = []
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "try_dispatch_mission_refresh_task",
        lambda _task, run_id, **_kwargs: dispatched.append(run_id) or True,
    )

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))

    manor = SimpleNamespace(mission_runs=_DueRunsManager(ids=[10, 11, 12]))

    mission_execution.refresh_mission_runs(manor)

    assert dispatched == [10, 11, 12]
    assert finalized == []


def test_refresh_mission_runs_falls_back_to_sync_for_failed_dispatch(monkeypatch):
    class _Status:
        ACTIVE = "active"

    runs = [SimpleNamespace(id=21), SimpleNamespace(id=22), SimpleNamespace(id=23)]
    mission_run_cls = type("_MissionRun", (), {"Status": _Status, "objects": _RunObjects(runs)})

    monkeypatch.setattr(mission_execution, "MissionRun", mission_run_cls)

    dispatch_ok = {21: True, 22: False, 23: True}
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "try_dispatch_mission_refresh_task",
        lambda _task, run_id, **_kwargs: dispatch_ok[run_id],
    )

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))

    manor = SimpleNamespace(mission_runs=_DueRunsManager(ids=[21, 22, 23]))

    mission_execution.refresh_mission_runs(manor, prefer_async=True)

    assert finalized == [22]


def test_refresh_mission_runs_nested_import_error_bubbles_up(monkeypatch):
    class _Status:
        ACTIVE = "active"

    mission_run_cls = type("_MissionRun", (), {"Status": _Status, "objects": _RunObjects([])})
    monkeypatch.setattr(mission_execution, "MissionRun", mission_run_cls)
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 0, raising=False)

    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            exc = ModuleNotFoundError("No module named 'redis'")
            exc.name = "redis"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    manor = SimpleNamespace(mission_runs=_DueRunsManager(ids=[31]))

    with pytest.raises(ModuleNotFoundError, match="redis"):
        mission_execution.refresh_mission_runs(manor, prefer_async=True)


def test_build_defender_setup_and_drop_table_sanitizes_invalid_mission_json():
    mission = SimpleNamespace(
        is_defense=False,
        enemy_guests="bad-guests",
        enemy_troops="bad-troops",
        enemy_technology="bad-tech",
        drop_table="bad-drops",
    )

    defender_setup, drop_table = mission_launch_post_actions.build_defender_setup_and_drop_table(
        mission,
        loadout={},
        normalize_guest_configs=mission_execution._normalize_guest_configs,
        normalize_mapping=mission_execution._normalize_mapping,
    )

    assert defender_setup["guest_keys"] == []
    assert defender_setup["troop_loadout"] == {}
    assert defender_setup["technology"] == {}
    assert drop_table == {}


def test_build_defender_setup_and_drop_table_for_defense_keeps_runtime_loadout():
    mission = SimpleNamespace(is_defense=True)
    loadout = {"archer": 10}

    defender_setup, drop_table = mission_launch_post_actions.build_defender_setup_and_drop_table(
        mission,
        loadout=loadout,
        normalize_guest_configs=mission_execution._normalize_guest_configs,
        normalize_mapping=mission_execution._normalize_mapping,
    )

    assert defender_setup == {"troop_loadout": loadout}
    assert drop_table == {}


def test_send_mission_report_message_ignores_explicit_message_failure(monkeypatch):
    run = SimpleNamespace(
        id=88,
        manor_id=9,
        is_retreating=False,
        manor=SimpleNamespace(user_id=100),
        mission=SimpleNamespace(key="mission_key", name="任务名"),
    )
    report = SimpleNamespace(id=66)

    monkeypatch.setattr(
        mission_execution,
        "create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )

    mission_execution.send_mission_report_message(
        run,
        report,
        logger=mission_execution.logger,
        create_message=mission_execution.create_message,
        notify_user=mission_execution.notify_user,
        notification_infrastructure_exceptions=mission_execution.MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
    )


def test_send_mission_report_message_runtime_marker_error_bubbles_up(monkeypatch):
    run = SimpleNamespace(
        id=188,
        manor_id=109,
        is_retreating=False,
        manor=SimpleNamespace(user_id=110),
        mission=SimpleNamespace(key="mission_key", name="任务名"),
    )
    report = SimpleNamespace(id=166)

    monkeypatch.setattr(
        mission_execution,
        "create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        mission_execution.send_mission_report_message(
            run,
            report,
            logger=mission_execution.logger,
            create_message=mission_execution.create_message,
            notify_user=mission_execution.notify_user,
            notification_infrastructure_exceptions=mission_execution.MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
        )


def test_send_mission_report_message_programming_error_bubbles_up(monkeypatch):
    run = SimpleNamespace(
        id=89,
        manor_id=10,
        is_retreating=False,
        manor=SimpleNamespace(user_id=101),
        mission=SimpleNamespace(key="mission_key", name="任务名"),
    )
    report = SimpleNamespace(id=67)

    monkeypatch.setattr(
        mission_execution,
        "create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken mission message contract")),
    )

    with pytest.raises(AssertionError, match="broken mission message contract"):
        mission_execution.send_mission_report_message(
            run,
            report,
            logger=mission_execution.logger,
            create_message=mission_execution.create_message,
            notify_user=mission_execution.notify_user,
            notification_infrastructure_exceptions=mission_execution.MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
        )


def test_send_mission_report_notification_programming_error_bubbles_up(monkeypatch):
    run = SimpleNamespace(
        id=90,
        manor_id=11,
        is_retreating=False,
        manor=SimpleNamespace(user_id=102),
        mission=SimpleNamespace(key="mission_key", name="任务名"),
    )
    report = SimpleNamespace(id=68)

    monkeypatch.setattr(mission_execution, "create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        mission_execution,
        "notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken mission notify contract")),
    )

    with pytest.raises(AssertionError, match="broken mission notify contract"):
        mission_execution.send_mission_report_message(
            run,
            report,
            logger=mission_execution.logger,
            create_message=mission_execution.create_message,
            notify_user=mission_execution.notify_user,
            notification_infrastructure_exceptions=mission_execution.MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
        )


def test_send_mission_report_notification_runtime_marker_error_bubbles_up(monkeypatch):
    run = SimpleNamespace(
        id=190,
        manor_id=111,
        is_retreating=False,
        manor=SimpleNamespace(user_id=112),
        mission=SimpleNamespace(key="mission_key", name="任务名"),
    )
    report = SimpleNamespace(id=168)

    monkeypatch.setattr(mission_execution, "create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        mission_execution,
        "notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        mission_execution.send_mission_report_message(
            run,
            report,
            logger=mission_execution.logger,
            create_message=mission_execution.create_message,
            notify_user=mission_execution.notify_user,
            notification_infrastructure_exceptions=mission_execution.MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
        )


def test_import_launch_post_action_tasks_falls_back_on_import_error(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"battle.tasks", "gameplay.tasks"}:
            exc = ModuleNotFoundError(f"No module named '{name}'")
            exc.name = name
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    generate_report_task, complete_mission_task = mission_launch_post_actions.import_launch_post_action_tasks(
        logger=mission_execution.logger
    )

    assert generate_report_task is None
    assert complete_mission_task is None


def test_import_launch_post_action_tasks_nested_import_error_bubbles_up(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "battle.tasks":
            exc = ModuleNotFoundError("No module named 'celery'")
            exc.name = "celery"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(ModuleNotFoundError, match="celery"):
        mission_launch_post_actions.import_launch_post_action_tasks(logger=mission_execution.logger)


def test_import_launch_post_action_tasks_unexpected_import_error_bubbles_up(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "battle.tasks":
            return SimpleNamespace(generate_report_task=object())
        if name == "gameplay.tasks":
            raise RuntimeError("broken gameplay task import")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(RuntimeError, match="broken gameplay task import"):
        mission_launch_post_actions.import_launch_post_action_tasks(logger=mission_execution.logger)


def test_schedule_mission_completion_task_finalizes_sync_when_due_dispatch_fails(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(id=51, return_at=now)
    finalized: list[int] = []

    monkeypatch.setattr(mission_execution.mission_followups, "safe_apply_async", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        mission_execution,
        "finalize_mission_run",
        lambda scheduled_run, **_kwargs: finalized.append(scheduled_run.id),
    )

    mission_execution.mission_followups.schedule_mission_completion_task(
        run,
        object(),
        logger=mission_execution.logger,
        finalize_mission_run=mission_execution.finalize_mission_run,
        now_func=timezone.now,
    )

    assert finalized == [51]


def test_schedule_mission_completion_finalizes_sync_when_due_task_import_fails(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(id=52, return_at=now)
    finalized: list[int] = []
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            exc = ModuleNotFoundError("No module named 'gameplay.tasks'")
            exc.name = "gameplay.tasks"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    monkeypatch.setattr(
        mission_execution,
        "finalize_mission_run",
        lambda scheduled_run, **_kwargs: finalized.append(scheduled_run.id),
    )

    mission_execution.schedule_mission_completion(run)

    assert finalized == [52]


def test_schedule_mission_completion_nested_import_error_bubbles_up(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(id=53, return_at=now)
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            exc = ModuleNotFoundError("No module named 'redis'")
            exc.name = "redis"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        mission_execution.schedule_mission_completion(run)
