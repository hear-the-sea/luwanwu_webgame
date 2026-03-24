from __future__ import annotations

import pytest
from django.utils import timezone

import gameplay.services.missions_impl.execution as mission_execution
import gameplay.services.missions_impl.refresh_command as mission_refresh_command
from tests.mission_refresh_async.support import missing_module_error, mission_run, patch_import


def test_schedule_mission_completion_task_finalizes_sync_when_due_dispatch_fails(monkeypatch):
    now = timezone.now()
    run = mission_run(51, return_at=now)
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


def test_schedule_mission_completion_task_rejects_past_return_at(monkeypatch):
    now = timezone.now()
    run = mission_run(151, return_at=now - timezone.timedelta(seconds=1))

    monkeypatch.setattr(mission_execution.mission_followups, "safe_apply_async", lambda *_args, **_kwargs: True)

    with pytest.raises(AssertionError, match="mission completion return_at cannot be in the past"):
        mission_execution.mission_followups.schedule_mission_completion_task(
            run,
            object(),
            logger=mission_execution.logger,
            finalize_mission_run=mission_execution.finalize_mission_run,
            now_func=lambda: now,
        )


def test_schedule_mission_completion_finalizes_sync_when_due_task_import_fails(monkeypatch):
    now = timezone.now()
    run = mission_run(52, return_at=now)
    finalized: list[int] = []

    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("gameplay.tasks", target="gameplay.tasks"))
            if name == "gameplay.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )
    monkeypatch.setattr(
        mission_execution,
        "finalize_mission_run",
        lambda scheduled_run, **_kwargs: finalized.append(scheduled_run.id),
    )

    mission_execution.schedule_mission_completion(run)

    assert finalized == [52]


def test_schedule_mission_completion_rejects_past_return_at():
    now = timezone.now()
    run = mission_run(152, return_at=now - timezone.timedelta(seconds=1))

    with pytest.raises(AssertionError, match="mission completion return_at cannot be in the past"):
        mission_refresh_command.schedule_mission_completion(
            run,
            logger=mission_execution.logger,
            now_func=lambda: now,
            safe_apply_async=lambda *_a, **_k: True,
            finalize_mission_run=lambda *_a, **_k: None,
        )


def test_schedule_mission_completion_rejects_missing_return_at():
    run = mission_run(153, return_at=None)

    with pytest.raises(RuntimeError, match="Mission run was not created correctly"):
        mission_refresh_command.schedule_mission_completion(
            run,
            logger=mission_execution.logger,
            now_func=timezone.now,
            safe_apply_async=lambda *_a, **_k: True,
            finalize_mission_run=lambda *_a, **_k: None,
        )


def test_schedule_mission_completion_nested_import_error_bubbles_up(monkeypatch):
    now = timezone.now()
    run = mission_run(53, return_at=now)

    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("redis", target="redis"))
            if name == "gameplay.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    with pytest.raises(ModuleNotFoundError, match="redis"):
        mission_execution.schedule_mission_completion(run)
