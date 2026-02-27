from __future__ import annotations

from types import SimpleNamespace

import gameplay.services.missions_impl.execution as mission_execution


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
        mission_execution,
        "_try_dispatch_mission_refresh_task",
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
        mission_execution,
        "_try_dispatch_mission_refresh_task",
        lambda _task, run_id: dispatched.append(run_id) or True,
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
        mission_execution,
        "_try_dispatch_mission_refresh_task",
        lambda _task, run_id: dispatch_ok[run_id],
    )

    finalized = []
    monkeypatch.setattr(mission_execution, "finalize_mission_run", lambda run, **_kwargs: finalized.append(run.id))

    manor = SimpleNamespace(mission_runs=_DueRunsManager(ids=[21, 22, 23]))

    mission_execution.refresh_mission_runs(manor, prefer_async=True)

    assert finalized == [22]


def test_build_defender_setup_and_drop_table_sanitizes_invalid_mission_json():
    mission = SimpleNamespace(
        is_defense=False,
        enemy_guests="bad-guests",
        enemy_troops="bad-troops",
        enemy_technology="bad-tech",
        drop_table="bad-drops",
    )

    defender_setup, drop_table = mission_execution._build_defender_setup_and_drop_table(mission, loadout={})

    assert defender_setup["guest_keys"] == []
    assert defender_setup["troop_loadout"] == {}
    assert defender_setup["technology"] == {}
    assert drop_table == {}


def test_build_defender_setup_and_drop_table_for_defense_keeps_runtime_loadout():
    mission = SimpleNamespace(is_defense=True)
    loadout = {"archer": 10}

    defender_setup, drop_table = mission_execution._build_defender_setup_and_drop_table(mission, loadout=loadout)

    assert defender_setup == {"troop_loadout": loadout}
    assert drop_table == {}


def test_send_mission_report_message_ignores_message_failure(monkeypatch):
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    mission_execution._send_mission_report_message(run, report)
