from __future__ import annotations

from types import SimpleNamespace

import pytest

import gameplay.services.missions_impl.execution as mission_execution
import gameplay.services.missions_impl.launch_post_actions as mission_launch_post_actions
from tests.mission_refresh_async.support import missing_module_error, patch_import


def test_import_launch_post_action_tasks_falls_back_on_import_error(monkeypatch):
    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error(name))
            if name in {"battle.tasks", "gameplay.tasks"}
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    generate_report_task, complete_mission_task = mission_launch_post_actions.import_launch_post_action_tasks(
        logger=mission_execution.logger
    )

    assert generate_report_task is None
    assert complete_mission_task is None


def test_import_launch_post_action_tasks_nested_import_error_bubbles_up(monkeypatch):
    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("celery", target="celery"))
            if name == "battle.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    with pytest.raises(ModuleNotFoundError, match="celery"):
        mission_launch_post_actions.import_launch_post_action_tasks(logger=mission_execution.logger)


def test_import_launch_post_action_tasks_unexpected_import_error_bubbles_up(monkeypatch):
    def _handler(name, globals, locals, fromlist, level, original_import):
        if name == "battle.tasks":
            return SimpleNamespace(generate_report_task=object())
        if name == "gameplay.tasks":
            raise RuntimeError("broken gameplay task import")
        return original_import(name, globals, locals, fromlist, level)

    patch_import(monkeypatch, _handler)

    with pytest.raises(RuntimeError, match="broken gameplay task import"):
        mission_launch_post_actions.import_launch_post_action_tasks(logger=mission_execution.logger)
