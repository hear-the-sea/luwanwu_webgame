from __future__ import annotations

import pytest

from gameplay.services.recruitment import lifecycle as troop_recruitment_lifecycle_service
from tests.troop_recruitment_service.support import missing_module_error, patch_import


def _recruitment_record(recruitment_id: int, *, manor_id: int, troop_key: str):
    return type("_Recruitment", (), {"id": recruitment_id, "manor_id": manor_id, "troop_key": troop_key})()


def test_schedule_recruitment_completion_runs_after_commit(monkeypatch):
    callbacks = []
    dispatched = []

    monkeypatch.setattr(
        troop_recruitment_lifecycle_service.transaction,
        "on_commit",
        lambda callback: callbacks.append(callback),
    )
    monkeypatch.setattr(
        "gameplay.tasks.complete_troop_recruitment",
        type("_Task", (), {"name": "gameplay.complete_troop_recruitment"})(),
    )
    monkeypatch.setattr(
        troop_recruitment_lifecycle_service,
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

    recruitment = _recruitment_record(17, manor_id=3, troop_key="scout")

    troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 45)

    assert len(callbacks) == 1
    assert dispatched == []

    callbacks[0]()

    assert dispatched == [
        {
            "task_name": "gameplay.complete_troop_recruitment",
            "args": [17],
            "countdown": 45,
        }
    ]


def test_schedule_recruitment_completion_unexpected_import_error_bubbles_up(monkeypatch):
    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(RuntimeError("broken task module"))
            if name == "gameplay.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    recruitment = _recruitment_record(17, manor_id=3, troop_key="scout")

    with pytest.raises(RuntimeError, match="broken task module"):
        troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 45)


def test_schedule_recruitment_completion_missing_target_module_degrades(monkeypatch):
    callbacks = []

    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("gameplay.tasks", target="gameplay.tasks"))
            if name == "gameplay.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )
    monkeypatch.setattr(
        troop_recruitment_lifecycle_service.transaction,
        "on_commit",
        lambda callback: callbacks.append(callback),
    )

    recruitment = _recruitment_record(19, manor_id=5, troop_key="scout")

    troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 30)

    assert callbacks == []


def test_schedule_recruitment_completion_nested_import_error_bubbles_up(monkeypatch):
    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("redis", target="redis"))
            if name == "gameplay.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    recruitment = _recruitment_record(18, manor_id=4, troop_key="archer")

    with pytest.raises(ModuleNotFoundError, match="redis"):
        troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 30)
