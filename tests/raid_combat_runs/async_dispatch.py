from __future__ import annotations

from types import SimpleNamespace

import pytest

from gameplay.services.raid.combat import battle as combat_battle
from gameplay.services.raid.combat import run_side_effects as combat_run_side_effects
from gameplay.services.raid.combat import runs as combat_runs


def test_dispatch_raid_battle_task_processes_sync_when_due_dispatch_fails(monkeypatch):
    processed: list[int] = []

    import gameplay.tasks as gameplay_tasks

    monkeypatch.setattr(gameplay_tasks, "process_raid_battle_task", object(), raising=False)
    monkeypatch.setattr(combat_runs, "safe_apply_async", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(combat_battle, "process_raid_battle", lambda run, **_kwargs: processed.append(run.id))

    combat_runs._dispatch_raid_battle_task(SimpleNamespace(id=123), travel_time=0)

    assert processed == [123]


def test_dispatch_raid_battle_task_nested_import_error_bubbles_up(monkeypatch):
    run = SimpleNamespace(id=123)

    def _raise_import():
        exc = ModuleNotFoundError("No module named 'redis'")
        exc.name = "redis"
        raise exc

    with pytest.raises(ModuleNotFoundError, match="redis"):
        combat_run_side_effects.dispatch_raid_battle_task_best_effort(
            run,
            0,
            logger=combat_runs.logger,
            import_process_raid_battle_task=_raise_import,
            safe_apply_async=lambda *_args, **_kwargs: True,
            process_raid_battle=lambda *_args, **_kwargs: None,
        )


def test_dispatch_raid_battle_task_missing_target_module_degrades_and_processes_sync_when_due():
    processed: list[int] = []
    run = SimpleNamespace(id=124)

    def _raise_import():
        exc = ModuleNotFoundError("No module named 'gameplay.tasks'")
        exc.name = "gameplay.tasks"
        raise exc

    combat_run_side_effects.dispatch_raid_battle_task_best_effort(
        run,
        0,
        logger=combat_runs.logger,
        import_process_raid_battle_task=_raise_import,
        safe_apply_async=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not dispatch when target task module is missing")
        ),
        process_raid_battle=lambda current_run, **_kwargs: processed.append(current_run.id),
    )

    assert processed == [124]


def test_dispatch_raid_battle_task_programming_error_bubbles_up():
    run = SimpleNamespace(id=125)

    with pytest.raises(AssertionError, match="broken task import contract"):
        combat_run_side_effects.dispatch_raid_battle_task_best_effort(
            run,
            0,
            logger=combat_runs.logger,
            import_process_raid_battle_task=lambda: (_ for _ in ()).throw(
                AssertionError("broken task import contract")
            ),
            safe_apply_async=lambda *_args, **_kwargs: True,
            process_raid_battle=lambda *_args, **_kwargs: None,
        )


def test_schedule_raid_retreat_completion_nested_import_error_bubbles_up():
    def _raise_import():
        exc = ModuleNotFoundError("No module named 'redis'")
        exc.name = "redis"
        raise exc

    with pytest.raises(ModuleNotFoundError, match="redis"):
        combat_run_side_effects.schedule_raid_retreat_completion_best_effort(
            55,
            30,
            logger=combat_runs.logger,
            import_complete_raid_task=_raise_import,
            safe_apply_async=lambda *_args, **_kwargs: True,
        )


def test_schedule_raid_retreat_completion_missing_target_module_degrades():
    def _raise_import():
        exc = ModuleNotFoundError("No module named 'gameplay.tasks'")
        exc.name = "gameplay.tasks"
        raise exc

    combat_run_side_effects.schedule_raid_retreat_completion_best_effort(
        56,
        30,
        logger=combat_runs.logger,
        import_complete_raid_task=_raise_import,
        safe_apply_async=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not dispatch when target task module is missing")
        ),
    )


def test_schedule_raid_retreat_completion_programming_error_bubbles_up():
    with pytest.raises(AssertionError, match="broken retreat task import contract"):
        combat_run_side_effects.schedule_raid_retreat_completion_best_effort(
            57,
            30,
            logger=combat_runs.logger,
            import_complete_raid_task=lambda: (_ for _ in ()).throw(
                AssertionError("broken retreat task import contract")
            ),
            safe_apply_async=lambda *_args, **_kwargs: True,
        )


def test_dispatch_async_raid_refresh_missing_target_module_falls_back_to_sync():
    def _raise_import():
        exc = ModuleNotFoundError("No module named 'gameplay.tasks'")
        exc.name = "gameplay.tasks"
        raise exc

    marching_ids, returning_ids, retreated_ids, done_async = combat_runs.dispatch_async_raid_refresh(
        [1, 2],
        [3],
        [4],
        logger=combat_runs.logger,
        import_tasks=_raise_import,
        dispatch_refresh_task=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not dispatch when target task module is missing")
        ),
    )

    assert (marching_ids, returning_ids, retreated_ids, done_async) == ([1, 2], [3], [4], False)


def test_dispatch_async_raid_refresh_programming_error_bubbles_up():
    with pytest.raises(AssertionError, match="broken refresh import contract"):
        combat_runs.dispatch_async_raid_refresh(
            [1],
            [],
            [],
            logger=combat_runs.logger,
            import_tasks=lambda: (_ for _ in ()).throw(AssertionError("broken refresh import contract")),
            dispatch_refresh_task=lambda *_args, **_kwargs: True,
        )
