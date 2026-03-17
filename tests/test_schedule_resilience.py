from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import transaction
from django.test import TestCase

import gameplay.services.technology as technology
from gameplay.services.buildings import forge, ranch, smithy, stable
from gameplay.services.manor import core as manor_core
from gameplay.services.recruitment import recruitment


class _FailingTask:
    def apply_async(self, *args, **kwargs):
        raise RuntimeError("broker down")


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
