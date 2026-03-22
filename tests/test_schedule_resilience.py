from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest
from django.db import transaction
from django.test import TestCase
from kombu.exceptions import OperationalError

import gameplay.services.technology as technology
from gameplay.services.buildings import forge, ranch, smithy, stable
from gameplay.services.manor import core as manor_core
from gameplay.services.recruitment import recruitment

_STRICT_IMPORT_SCHEDULERS = [
    manor_core.schedule_building_completion,
    technology.schedule_technology_completion,
    stable._schedule_production_completion,
    ranch._schedule_livestock_completion,
    smithy._schedule_smelting_completion,
    forge._schedule_forging_completion,
]


class _FailingTask:
    def apply_async(self, *args, **kwargs):
        raise OperationalError("dispatch failed")


@pytest.mark.parametrize(
    ("scheduler", "task_attr", "obj_id"),
    [
        (manor_core.schedule_building_completion, "complete_building_upgrade", 1),
        (technology.schedule_technology_completion, "complete_technology_upgrade", 2),
        (recruitment._schedule_recruitment_completion, "complete_troop_recruitment", 3),
        (stable._schedule_production_completion, "complete_horse_production", 4),
        (ranch._schedule_livestock_completion, "complete_livestock_production", 5),
        (smithy._schedule_smelting_completion, "complete_smelting_production", 6),
        (forge._schedule_forging_completion, "complete_equipment_forging", 7),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_schedule_callbacks_do_not_raise_on_dispatch_failure(monkeypatch, scheduler, task_attr, obj_id):
    import gameplay.tasks as gameplay_tasks

    monkeypatch.setattr(gameplay_tasks, task_attr, _FailingTask(), raising=False)

    with transaction.atomic():
        with TestCase.captureOnCommitCallbacks(execute=True) as callbacks:
            scheduler(SimpleNamespace(id=obj_id), 30)

        assert len(callbacks) == 1


@pytest.mark.parametrize(
    "scheduler",
    _STRICT_IMPORT_SCHEDULERS,
)
def test_schedule_callbacks_unexpected_import_error_bubbles_up(monkeypatch, scheduler):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            raise RuntimeError("broken task module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(RuntimeError, match="broken task module"):
        scheduler(SimpleNamespace(id=1), 30)


@pytest.mark.parametrize(
    "scheduler",
    _STRICT_IMPORT_SCHEDULERS,
)
def test_schedule_callbacks_missing_target_module_degrades(monkeypatch, scheduler):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            exc = ModuleNotFoundError("No module named 'gameplay.tasks'")
            exc.name = "gameplay.tasks"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    callbacks = []
    monkeypatch.setattr(transaction, "on_commit", lambda callback: callbacks.append(callback))

    scheduler(SimpleNamespace(id=1), 30)

    assert callbacks == []


@pytest.mark.parametrize(
    "scheduler",
    _STRICT_IMPORT_SCHEDULERS,
)
def test_schedule_callbacks_nested_import_error_bubbles_up(monkeypatch, scheduler):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            exc = ModuleNotFoundError("No module named 'redis'")
            exc.name = "redis"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        scheduler(SimpleNamespace(id=1), 30)
