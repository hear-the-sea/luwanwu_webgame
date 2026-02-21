from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

import gameplay.tasks as tasks


class _Chain:
    def __init__(self, *, first_result=None, slice_result=None):
        self._first_result = first_result
        self._slice_result = slice_result or []

    def select_related(self, *args, **kwargs):
        return self

    def prefetch_related(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_result

    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(self._slice_result)
        raise TypeError("Only slicing is supported")


def _patch_model(monkeypatch, dotted_path: str, *, first_result=None, slice_result=None, status_cls=None) -> None:
    attrs = {"objects": _Chain(first_result=first_result, slice_result=slice_result)}
    if status_cls is not None:
        attrs["Status"] = status_cls
    dummy_cls = type("_DummyModel", (), attrs)
    monkeypatch.setattr(dotted_path, dummy_cls)


@pytest.mark.django_db
def test_complete_mission_task_not_found(monkeypatch):
    monkeypatch.setattr("gameplay.tasks.missions.MissionRun", SimpleNamespace(objects=_Chain(first_result=None)))

    assert tasks.complete_mission_task.run(123) == "not_found"


@pytest.mark.django_db
def test_complete_mission_task_reschedules_when_not_due(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(return_at=now + timedelta(seconds=10))

    monkeypatch.setattr("gameplay.tasks.missions.MissionRun", SimpleNamespace(objects=_Chain(first_result=run)))
    finalize = []
    monkeypatch.setattr("gameplay.tasks.missions.finalize_mission_run", lambda *_args, **_kwargs: finalize.append(True))

    called = {}

    def _apply_async(*, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown

    monkeypatch.setattr(tasks.complete_mission_task, "apply_async", _apply_async)

    assert tasks.complete_mission_task.run(1) == "rescheduled"
    assert called["args"] == [1]
    assert called["countdown"] > 0
    assert not finalize


@pytest.mark.django_db
def test_complete_building_upgrade_completes_or_skips(monkeypatch):
    now = timezone.now()
    building = SimpleNamespace(upgrade_complete_at=now - timedelta(seconds=1), id=7)

    class _Building:
        objects = _Chain(first_result=building)

    monkeypatch.setattr("gameplay.models.Building", _Building)
    monkeypatch.setattr("gameplay.tasks.buildings.finalize_building_upgrade", lambda *_args, **_kwargs: True)

    assert tasks.complete_building_upgrade.run(7) == "completed"

    monkeypatch.setattr("gameplay.tasks.buildings.finalize_building_upgrade", lambda *_args, **_kwargs: False)
    assert tasks.complete_building_upgrade.run(7) == "skipped"


@pytest.mark.django_db
def test_scan_building_upgrades_counts_successes(monkeypatch):
    buildings = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]

    class _Building:
        objects = _Chain(slice_result=buildings)

    monkeypatch.setattr("gameplay.models.Building", _Building)

    def _finalize(building, **_kwargs):
        if building.id == 2:
            raise RuntimeError("boom")
        return building.id != 3

    monkeypatch.setattr("gameplay.tasks.buildings.finalize_building_upgrade", _finalize)

    assert tasks.scan_building_upgrades() == 1


@pytest.mark.django_db
def test_complete_work_assignments_task_returns_count(monkeypatch):
    monkeypatch.setattr("gameplay.services.work.complete_work_assignments", lambda: 3)
    assert tasks.complete_work_assignments_task.run() == "完成 3 个打工任务"


@pytest.mark.django_db
def test_complete_horse_production_reschedules(monkeypatch):
    now = timezone.now()
    production = SimpleNamespace(complete_at=now + timedelta(seconds=9))

    class _HorseProduction:
        class Status:
            PRODUCING = "producing"

        objects = _Chain(first_result=production)

    monkeypatch.setattr("gameplay.models.HorseProduction", _HorseProduction)
    monkeypatch.setattr("gameplay.services.buildings.stable.finalize_horse_production", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)

    called = {}

    def _apply_async(*, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown

    monkeypatch.setattr(tasks.complete_horse_production, "apply_async", _apply_async)

    assert tasks.complete_horse_production.run(99) == "rescheduled"
    assert called["args"] == [99]
    assert called["countdown"] > 0


@pytest.mark.django_db
def test_scan_troop_recruitments_counts(monkeypatch):
    recruitments = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    class _TroopRecruitment:
        class Status:
            RECRUITING = "recruiting"

        objects = _Chain(slice_result=recruitments)

    monkeypatch.setattr("gameplay.models.TroopRecruitment", _TroopRecruitment)
    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment.finalize_troop_recruitment",
        lambda recruitment, **_kwargs: recruitment.id == 2,
    )

    assert tasks.scan_troop_recruitments() == 1


@pytest.mark.django_db
def test_complete_technology_upgrade_reschedules(monkeypatch):
    now = timezone.now()
    tech = SimpleNamespace(upgrade_complete_at=now + timedelta(seconds=10))

    _patch_model(monkeypatch, "gameplay.models.PlayerTechnology", first_result=tech)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    monkeypatch.setattr(tasks, "finalize_technology_upgrade", lambda *_args, **_kwargs: True)

    called = {}

    def _apply_async(*, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown

    monkeypatch.setattr(tasks.complete_technology_upgrade, "apply_async", _apply_async)

    assert tasks.complete_technology_upgrade.run(5) == "rescheduled"
    assert called["args"] == [5]
    assert called["countdown"] > 0


@pytest.mark.django_db
def test_scan_technology_upgrades_counts(monkeypatch):
    techs = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]

    class _Status:
        UPGRADING = "upgrading"

    _patch_model(monkeypatch, "gameplay.models.PlayerTechnology", slice_result=techs, status_cls=_Status)

    def _finalize(tech, **_kwargs):
        return tech.id in {1, 3}

    monkeypatch.setattr("gameplay.tasks.technology.finalize_technology_upgrade", _finalize)

    assert tasks.scan_technology_upgrades() == 2


@pytest.mark.django_db
def test_complete_livestock_production_not_found(monkeypatch):
    _patch_model(monkeypatch, "gameplay.models.LivestockProduction", first_result=None)
    monkeypatch.setattr(
        "gameplay.services.buildings.ranch.finalize_livestock_production", lambda *_args, **_kwargs: True
    )
    assert tasks.complete_livestock_production.run(1) == "not_found"


@pytest.mark.django_db
def test_scan_smelting_productions_counts(monkeypatch):
    productions = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    class _Status:
        PRODUCING = "producing"

    _patch_model(monkeypatch, "gameplay.models.SmeltingProduction", slice_result=productions, status_cls=_Status)
    monkeypatch.setattr(
        "gameplay.services.buildings.smithy.finalize_smelting_production",
        lambda production, **_kwargs: production.id == 2,
    )

    assert tasks.scan_smelting_productions() == 1


@pytest.mark.django_db
def test_scan_scout_records_counts_both_phases(monkeypatch):
    scouting = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    returning = [SimpleNamespace(id=3)]

    class _Status:
        SCOUTING = "scouting"
        RETURNING = "returning"

    class _ScoutObjects:
        def __init__(self):
            self._status = None

        def select_related(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            self._status = kwargs.get("status")
            return self

        def order_by(self, *args, **kwargs):
            return self

        def __getitem__(self, item):
            if self._status == _Status.SCOUTING:
                return list(scouting)
            if self._status == _Status.RETURNING:
                return list(returning)
            return []

    dummy_cls = type("_ScoutRecord", (), {"objects": _ScoutObjects(), "Status": _Status})
    monkeypatch.setattr("gameplay.models.ScoutRecord", dummy_cls)

    called = {"scout": 0, "return": 0}

    def _finalize_scout(*_args, **_kwargs):
        called["scout"] += 1

    def _finalize_return(*_args, **_kwargs):
        called["return"] += 1

    monkeypatch.setattr("gameplay.services.raid.finalize_scout", _finalize_scout)
    monkeypatch.setattr("gameplay.services.raid.finalize_scout_return", _finalize_return)

    assert tasks.scan_scout_records() == 3
    assert called["scout"] == 2
    assert called["return"] == 1
