from __future__ import annotations

from types import SimpleNamespace

import pytest

import gameplay.services.missions_impl.execution as mission_execution
from tests.mission_refresh_async.support import (
    DueRunsManager,
    build_mission_run_cls,
    missing_module_error,
    patch_import,
)


def test_refresh_mission_runs_uses_sync_for_small_backlog(monkeypatch):
    runs = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    monkeypatch.setattr(mission_execution, "MissionRun", build_mission_run_cls(runs))
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 3, raising=False)

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "try_dispatch_mission_refresh_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not dispatch async")),
    )

    manor = SimpleNamespace(mission_runs=DueRunsManager(ids=[1, 2]))

    mission_execution.refresh_mission_runs(manor)

    assert finalized == [1, 2]


def test_refresh_mission_runs_dispatches_async_for_large_backlog(monkeypatch):
    monkeypatch.setattr(mission_execution, "MissionRun", build_mission_run_cls([]))
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 2, raising=False)

    dispatched = []
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "try_dispatch_mission_refresh_task",
        lambda _task, run_id, **_kwargs: dispatched.append(run_id) or True,
    )

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))

    manor = SimpleNamespace(mission_runs=DueRunsManager(ids=[10, 11, 12]))

    mission_execution.refresh_mission_runs(manor)

    assert dispatched == [10, 11, 12]
    assert finalized == []


def test_refresh_mission_runs_falls_back_to_sync_for_failed_dispatch(monkeypatch):
    runs = [SimpleNamespace(id=21), SimpleNamespace(id=22), SimpleNamespace(id=23)]
    monkeypatch.setattr(mission_execution, "MissionRun", build_mission_run_cls(runs))

    dispatch_ok = {21: True, 22: False, 23: True}
    monkeypatch.setattr(
        mission_execution.mission_followups,
        "try_dispatch_mission_refresh_task",
        lambda _task, run_id, **_kwargs: dispatch_ok[run_id],
    )

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))

    manor = SimpleNamespace(mission_runs=DueRunsManager(ids=[21, 22, 23]))

    mission_execution.refresh_mission_runs(manor, prefer_async=True)

    assert finalized == [22]


def test_refresh_mission_runs_nested_import_error_bubbles_up(monkeypatch):
    monkeypatch.setattr(mission_execution, "MissionRun", build_mission_run_cls([]))
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 0, raising=False)

    def _import_handler(name, _globals, _locals, _fromlist, _level, _original_import):
        if name == "gameplay.tasks":
            raise missing_module_error("redis", target="redis")
        return mission_execution

    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("redis", target="redis"))
            if name == "gameplay.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )
    manor = SimpleNamespace(mission_runs=DueRunsManager(ids=[31]))

    with pytest.raises(ModuleNotFoundError, match="redis"):
        mission_execution.refresh_mission_runs(manor, prefer_async=True)


def test_refresh_mission_runs_rejects_invalid_sync_max_runs_type(monkeypatch):
    monkeypatch.setattr(mission_execution, "MissionRun", build_mission_run_cls([]))
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", "bad", raising=False)

    manor = SimpleNamespace(mission_runs=DueRunsManager(ids=[1]))

    with pytest.raises(AssertionError, match="invalid mission refresh sync max runs"):
        mission_execution.refresh_mission_runs(manor)


def test_refresh_mission_runs_rejects_negative_sync_max_runs(monkeypatch):
    monkeypatch.setattr(mission_execution, "MissionRun", build_mission_run_cls([]))
    monkeypatch.setattr(mission_execution.settings, "MISSION_REFRESH_SYNC_MAX_RUNS", -1, raising=False)

    manor = SimpleNamespace(mission_runs=DueRunsManager(ids=[1]))

    with pytest.raises(AssertionError, match="invalid mission refresh sync max runs"):
        mission_execution.refresh_mission_runs(manor)
