from __future__ import annotations

import pytest

from guests.services import recruitment_followups as recruitment_followups_service
from tests.guests.support import missing_module_error, patch_import


def _recruitment_record(recruitment_id: int, *, manor_id: int, pool_id: int):
    return type("_Recruitment", (), {"id": recruitment_id, "manor_id": manor_id, "pool_id": pool_id})()


def test_schedule_guest_recruitment_completion_runs_after_commit(monkeypatch):
    callbacks = []
    dispatched = []

    monkeypatch.setattr(
        recruitment_followups_service.transaction,
        "on_commit",
        lambda callback: callbacks.append(callback),
    )
    monkeypatch.setattr(
        "guests.tasks.complete_guest_recruitment",
        type("_Task", (), {"name": "guests.complete_recruitment"})(),
    )
    monkeypatch.setattr(
        recruitment_followups_service,
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

    recruitment = _recruitment_record(17, manor_id=3, pool_id=5)

    recruitment_followups_service.schedule_guest_recruitment_completion(
        recruitment,
        45,
        logger=recruitment_followups_service.logging.getLogger(__name__),
    )

    assert len(callbacks) == 1
    assert dispatched == []

    callbacks[0]()

    assert dispatched == [
        {
            "task_name": "guests.complete_recruitment",
            "args": [17],
            "countdown": 45,
        }
    ]


def test_schedule_guest_recruitment_completion_rejects_negative_eta():
    recruitment = _recruitment_record(17, manor_id=3, pool_id=5)

    with pytest.raises(AssertionError, match="invalid guest recruitment completion eta"):
        recruitment_followups_service.schedule_guest_recruitment_completion(
            recruitment,
            -1,
            logger=recruitment_followups_service.logging.getLogger(__name__),
        )


def test_schedule_guest_recruitment_completion_unexpected_import_error_bubbles_up(monkeypatch):
    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(RuntimeError("broken task module"))
            if name == "guests.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    recruitment = _recruitment_record(17, manor_id=3, pool_id=5)

    with pytest.raises(RuntimeError, match="broken task module"):
        recruitment_followups_service.schedule_guest_recruitment_completion(
            recruitment,
            45,
            logger=recruitment_followups_service.logging.getLogger(__name__),
        )


def test_schedule_guest_recruitment_completion_nested_import_error_bubbles_up(monkeypatch):
    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("redis", target="redis"))
            if name == "guests.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )

    recruitment = _recruitment_record(18, manor_id=4, pool_id=6)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        recruitment_followups_service.schedule_guest_recruitment_completion(
            recruitment,
            30,
            logger=recruitment_followups_service.logging.getLogger(__name__),
        )


def test_schedule_guest_recruitment_completion_missing_target_module_degrades(monkeypatch):
    callbacks = []

    patch_import(
        monkeypatch,
        lambda name, globals, locals, fromlist, level, original_import: (
            (_ for _ in ()).throw(missing_module_error("guests.tasks", target="guests.tasks"))
            if name == "guests.tasks"
            else original_import(name, globals, locals, fromlist, level)
        ),
    )
    monkeypatch.setattr(
        recruitment_followups_service.transaction,
        "on_commit",
        lambda callback: callbacks.append(callback),
    )

    recruitment = _recruitment_record(19, manor_id=5, pool_id=7)

    recruitment_followups_service.schedule_guest_recruitment_completion(
        recruitment,
        20,
        logger=recruitment_followups_service.logging.getLogger(__name__),
    )

    assert callbacks == []
