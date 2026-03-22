from __future__ import annotations

import builtins
import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import OperationalError
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
def test_complete_mission_task_reschedules_with_ceil_for_fractional_remaining(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(return_at=now + timedelta(milliseconds=250))

    monkeypatch.setattr("gameplay.tasks.missions.MissionRun", SimpleNamespace(objects=_Chain(first_result=run)))
    monkeypatch.setattr("gameplay.tasks.missions.timezone.now", lambda: now)

    called = {}

    def _safe_apply_async_with_dedup(*_args, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown
        return True

    monkeypatch.setattr("gameplay.tasks.missions.safe_apply_async_with_dedup", _safe_apply_async_with_dedup)

    assert tasks.complete_mission_task.run(101) == "rescheduled"
    assert called["args"] == [101]
    assert called["countdown"] == 1


@pytest.mark.django_db
def test_complete_mission_task_retries_when_reschedule_dispatch_fails(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(return_at=now + timedelta(seconds=5))

    monkeypatch.setattr("gameplay.tasks.missions.MissionRun", SimpleNamespace(objects=_Chain(first_result=run)))
    monkeypatch.setattr("gameplay.tasks.missions.safe_apply_async_with_dedup", lambda *_args, **_kwargs: False)

    retried = {}

    def _retry(*, exc=None, **_kwargs):
        retried["exc"] = exc
        raise RuntimeError("retry requested")

    monkeypatch.setattr(tasks.complete_mission_task, "retry", _retry)

    with pytest.raises(RuntimeError, match="retry requested"):
        tasks.complete_mission_task.run(102)

    assert "mission reschedule dispatch failed" in str(retried["exc"])


@pytest.mark.django_db
def test_complete_mission_task_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()
    run = SimpleNamespace(return_at=now - timedelta(seconds=1))

    monkeypatch.setattr("gameplay.tasks.missions.MissionRun", SimpleNamespace(objects=_Chain(first_result=run)))
    monkeypatch.setattr(
        "gameplay.tasks.missions.finalize_mission_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken mission finalize contract")),
    )
    monkeypatch.setattr(
        tasks.complete_mission_task,
        "retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    with pytest.raises(AssertionError, match="broken mission finalize contract"):
        tasks.complete_mission_task.run(103)


@pytest.mark.django_db
def test_scan_due_missions_programming_error_bubbles_up(monkeypatch):
    now = timezone.now()
    runs = [SimpleNamespace(id=1, pk=1)]

    class _Status:
        ACTIVE = "active"

    _patch_model(monkeypatch, "gameplay.tasks.missions.MissionRun", slice_result=runs, status_cls=_Status)
    monkeypatch.setattr("gameplay.tasks.missions.timezone.now", lambda: now)
    monkeypatch.setattr(
        "gameplay.tasks.missions.finalize_mission_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken mission scan contract")),
    )

    with pytest.raises(AssertionError, match="broken mission scan contract"):
        tasks.scan_due_missions()


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
def test_complete_building_upgrade_reschedules_when_fractional_remaining(monkeypatch):
    now = timezone.now()
    building = SimpleNamespace(upgrade_complete_at=now + timedelta(milliseconds=300), id=8)

    class _Building:
        objects = _Chain(first_result=building)

    monkeypatch.setattr("gameplay.models.Building", _Building)
    monkeypatch.setattr("gameplay.tasks.buildings.timezone.now", lambda: now)

    finalized = []
    monkeypatch.setattr(
        "gameplay.tasks.buildings.finalize_building_upgrade",
        lambda *_args, **_kwargs: finalized.append(True),
    )

    called = {}

    def _safe_apply_async_with_dedup(*_args, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown
        return True

    monkeypatch.setattr("gameplay.tasks.buildings.safe_apply_async_with_dedup", _safe_apply_async_with_dedup)

    assert tasks.complete_building_upgrade.run(8) == "rescheduled"
    assert called["args"] == [8]
    assert called["countdown"] == 1
    assert not finalized


@pytest.mark.django_db
def test_scan_building_upgrades_counts_successes(monkeypatch):
    buildings = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]

    class _Building:
        objects = _Chain(slice_result=buildings)

    monkeypatch.setattr("gameplay.models.Building", _Building)

    def _finalize(building, **_kwargs):
        if building.id == 2:
            raise OperationalError("db down")
        return building.id != 3

    monkeypatch.setattr("gameplay.tasks.buildings.finalize_building_upgrade", _finalize)

    assert tasks.scan_building_upgrades() == 1


@pytest.mark.django_db
def test_complete_building_upgrade_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()
    building = SimpleNamespace(upgrade_complete_at=now - timedelta(seconds=1), id=9)

    class _Building:
        objects = _Chain(first_result=building)

    monkeypatch.setattr("gameplay.models.Building", _Building)
    monkeypatch.setattr(
        "gameplay.tasks.buildings.complete_building_upgrade.retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "gameplay.tasks.buildings.finalize_building_upgrade",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken building finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken building finalize contract"):
        tasks.complete_building_upgrade.run(9)


@pytest.mark.django_db
def test_scan_building_upgrades_programming_error_bubbles_up(monkeypatch):
    buildings = [SimpleNamespace(id=1)]

    class _Building:
        objects = _Chain(slice_result=buildings)

    monkeypatch.setattr("gameplay.models.Building", _Building)
    monkeypatch.setattr(
        "gameplay.tasks.buildings.finalize_building_upgrade",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken building scan contract")),
    )

    with pytest.raises(AssertionError, match="broken building scan contract"):
        tasks.scan_building_upgrades()


@pytest.mark.django_db
def test_complete_work_assignments_task_returns_count(monkeypatch):
    monkeypatch.setattr("gameplay.services.work.complete_work_assignments", lambda: 3)
    assert tasks.complete_work_assignments_task.run() == "完成 3 个打工任务"


@pytest.mark.django_db
def test_complete_work_assignments_task_programming_error_bubbles_up(monkeypatch):
    monkeypatch.setattr(
        "gameplay.services.work.complete_work_assignments",
        lambda: (_ for _ in ()).throw(AssertionError("broken work completion contract")),
    )

    with pytest.raises(AssertionError, match="broken work completion contract"):
        tasks.complete_work_assignments_task.run()


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
def test_complete_horse_production_reschedules_with_ceil_for_fractional_remaining(monkeypatch):
    now = timezone.now()
    production = SimpleNamespace(complete_at=now + timedelta(milliseconds=200))

    class _HorseProduction:
        class Status:
            PRODUCING = "producing"

        objects = _Chain(first_result=production)

    monkeypatch.setattr("gameplay.models.HorseProduction", _HorseProduction)
    monkeypatch.setattr("gameplay.tasks.production.timezone.now", lambda: now)

    called = {}

    def _safe_apply_async_with_dedup(*_args, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown
        return True

    monkeypatch.setattr("gameplay.tasks.production.safe_apply_async_with_dedup", _safe_apply_async_with_dedup)

    assert tasks.complete_horse_production.run(103) == "rescheduled"
    assert called["args"] == [103]
    assert called["countdown"] == 1


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
def test_complete_troop_recruitment_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()
    recruitment = SimpleNamespace(complete_at=now - timedelta(seconds=1), id=21)
    _patch_model(monkeypatch, "gameplay.models.TroopRecruitment", first_result=recruitment)
    monkeypatch.setattr(
        "gameplay.tasks.recruitment.complete_troop_recruitment.retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment.finalize_troop_recruitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken troop recruitment finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken troop recruitment finalize contract"):
        tasks.complete_troop_recruitment.run(21)


@pytest.mark.django_db
def test_scan_troop_recruitments_programming_error_bubbles_up(monkeypatch):
    recruitments = [SimpleNamespace(id=1)]

    class _TroopRecruitment:
        class Status:
            RECRUITING = "recruiting"

        objects = _Chain(slice_result=recruitments)

    monkeypatch.setattr("gameplay.models.TroopRecruitment", _TroopRecruitment)
    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment.finalize_troop_recruitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken troop recruitment scan contract")),
    )

    with pytest.raises(AssertionError, match="broken troop recruitment scan contract"):
        tasks.scan_troop_recruitments()


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
def test_complete_technology_upgrade_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()
    tech = SimpleNamespace(upgrade_complete_at=now - timedelta(seconds=1), id=5)

    _patch_model(monkeypatch, "gameplay.models.PlayerTechnology", first_result=tech)
    monkeypatch.setattr(
        "gameplay.tasks.technology.complete_technology_upgrade.retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "gameplay.tasks.technology.finalize_technology_upgrade",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken technology finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken technology finalize contract"):
        tasks.complete_technology_upgrade.run(5)


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
def test_scan_technology_upgrades_programming_error_bubbles_up(monkeypatch):
    techs = [SimpleNamespace(id=1)]

    class _Status:
        UPGRADING = "upgrading"

    _patch_model(monkeypatch, "gameplay.models.PlayerTechnology", slice_result=techs, status_cls=_Status)
    monkeypatch.setattr(
        "gameplay.tasks.technology.finalize_technology_upgrade",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken technology scan contract")),
    )

    with pytest.raises(AssertionError, match="broken technology scan contract"):
        tasks.scan_technology_upgrades()


@pytest.mark.django_db
def test_complete_livestock_production_not_found(monkeypatch):
    _patch_model(monkeypatch, "gameplay.models.LivestockProduction", first_result=None)
    monkeypatch.setattr(
        "gameplay.services.buildings.ranch.finalize_livestock_production", lambda *_args, **_kwargs: True
    )
    assert tasks.complete_livestock_production.run(1) == "not_found"


@pytest.mark.django_db
def test_complete_horse_production_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()
    production = SimpleNamespace(complete_at=now - timedelta(seconds=1), id=110)

    class _HorseProduction:
        class Status:
            PRODUCING = "producing"

        objects = _Chain(first_result=production)

    monkeypatch.setattr("gameplay.models.HorseProduction", _HorseProduction)
    monkeypatch.setattr(
        "gameplay.tasks.production.complete_horse_production.retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "gameplay.services.buildings.stable.finalize_horse_production",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken horse finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken horse finalize contract"):
        tasks.complete_horse_production.run(110)


@pytest.mark.django_db
def test_complete_horse_production_retries_for_database_infrastructure_error(monkeypatch):
    now = timezone.now()
    production = SimpleNamespace(complete_at=now - timedelta(seconds=1), id=111)

    class _HorseProduction:
        class Status:
            PRODUCING = "producing"

        objects = _Chain(first_result=production)

    monkeypatch.setattr("gameplay.models.HorseProduction", _HorseProduction)
    monkeypatch.setattr(
        "gameplay.services.buildings.stable.finalize_horse_production",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OperationalError("db down")),
    )

    retried = {}

    def _retry(*, exc=None, **_kwargs):
        retried["exc"] = exc
        raise RuntimeError("retry requested")

    monkeypatch.setattr("gameplay.tasks.production.complete_horse_production.retry", _retry)

    with pytest.raises(RuntimeError, match="retry requested"):
        tasks.complete_horse_production.run(111)

    assert isinstance(retried["exc"], OperationalError)


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
def test_scan_horse_productions_programming_error_bubbles_up(monkeypatch):
    productions = [SimpleNamespace(id=1)]

    class _Status:
        PRODUCING = "producing"

    _patch_model(monkeypatch, "gameplay.models.HorseProduction", slice_result=productions, status_cls=_Status)
    monkeypatch.setattr(
        "gameplay.services.buildings.stable.finalize_horse_production",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken horse scan contract")),
    )

    with pytest.raises(AssertionError, match="broken horse scan contract"):
        tasks.scan_horse_productions()


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


@pytest.mark.django_db
def test_complete_scout_task_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()

    class _Status:
        SCOUTING = "scouting"

    record = SimpleNamespace(status=_Status.SCOUTING, complete_at=now - timedelta(seconds=1))
    monkeypatch.setattr(
        "gameplay.models.ScoutRecord",
        SimpleNamespace(objects=_Chain(first_result=record), Status=_Status),
    )
    monkeypatch.setattr("gameplay.tasks.pvp.timezone.now", lambda: now)
    monkeypatch.setattr(
        "gameplay.tasks.pvp.complete_scout_task.retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.finalize_scout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken scout finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken scout finalize contract"):
        tasks.complete_scout_task.run(301)


@pytest.mark.django_db
def test_complete_raid_task_programming_error_bubbles_without_retry(monkeypatch):
    now = timezone.now()

    class _Status:
        COMPLETED = "completed"
        RETREATED = "retreated"
        RETURNING = "returning"

    run = SimpleNamespace(status=_Status.RETURNING, return_at=now - timedelta(seconds=1))
    monkeypatch.setattr(
        "gameplay.models.RaidRun",
        SimpleNamespace(objects=_Chain(first_result=run), Status=_Status),
    )
    monkeypatch.setattr("gameplay.tasks.pvp.timezone.now", lambda: now)
    monkeypatch.setattr(
        "gameplay.tasks.pvp.complete_raid_task.retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.finalize_raid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken raid finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken raid finalize contract"):
        tasks.complete_raid_task.run(302)


@pytest.mark.django_db
def test_scan_raid_runs_programming_error_bubbles_up(monkeypatch):
    now = timezone.now()
    marching = [SimpleNamespace(id=11)]
    returning = []
    retreated = []

    class _Status:
        MARCHING = "marching"
        RETURNING = "returning"
        RETREATED = "retreated"

    class _RaidObjects:
        def __init__(self):
            self._status = None

        def select_related(self, *args, **kwargs):
            return self

        def prefetch_related(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            self._status = kwargs.get("status")
            return self

        def order_by(self, *args, **kwargs):
            return self

        def __getitem__(self, item):
            if self._status == _Status.MARCHING:
                return list(marching)
            if self._status == _Status.RETURNING:
                return list(returning)
            if self._status == _Status.RETREATED:
                return list(retreated)
            return []

    monkeypatch.setattr(
        "gameplay.models.RaidRun",
        type("_RaidRun", (), {"objects": _RaidObjects(), "Status": _Status}),
    )
    monkeypatch.setattr("gameplay.tasks.pvp.timezone.now", lambda: now)
    monkeypatch.setattr(
        "gameplay.services.raid.process_raid_battle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken raid scan contract")),
    )

    with pytest.raises(AssertionError, match="broken raid scan contract"):
        tasks.scan_raid_runs()


@pytest.mark.django_db
def test_guest_training_fractional_remaining(monkeypatch):
    import guests.tasks as guest_tasks

    now = timezone.now()
    guest = SimpleNamespace(training_complete_at=now + timedelta(milliseconds=300))

    monkeypatch.setattr("guests.models.Guest", SimpleNamespace(objects=_Chain(first_result=guest)))
    monkeypatch.setattr("guests.tasks.timezone.now", lambda: now)

    finalized = []
    monkeypatch.setattr(
        "guests.services.training.finalize_guest_training", lambda *_args, **_kwargs: finalized.append(True)
    )

    called = {}

    def _safe_apply_async_with_dedup(*_args, args=None, countdown=None, **_kwargs):
        called["args"] = args
        called["countdown"] = countdown
        return True

    monkeypatch.setattr("guests.tasks.safe_apply_async_with_dedup", _safe_apply_async_with_dedup)

    assert guest_tasks.complete_guest_training.run(101) == "rescheduled"
    assert called["args"] == [101]
    assert called["countdown"] == 1
    assert not finalized


@pytest.mark.django_db
def test_guest_training_dispatch_false(monkeypatch, caplog):
    import guests.tasks as guest_tasks

    now = timezone.now()
    guest = SimpleNamespace(training_complete_at=now + timedelta(seconds=5))

    monkeypatch.setattr("guests.models.Guest", SimpleNamespace(objects=_Chain(first_result=guest)))
    monkeypatch.setattr("guests.tasks.timezone.now", lambda: now)
    monkeypatch.setattr("guests.tasks.safe_apply_async_with_dedup", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("guests.services.training.finalize_guest_training", lambda *_args, **_kwargs: False)

    with caplog.at_level(logging.WARNING):
        assert guest_tasks.complete_guest_training.run(102) == "reschedule_failed"

    assert "guest training reschedule dispatch returned False: guest_id=102" in caplog.text


@pytest.mark.django_db
def test_guest_training_runtime_marker_bubbles_up_without_retry(monkeypatch):
    import guests.tasks as guest_tasks

    guest = SimpleNamespace(training_complete_at=None)

    monkeypatch.setattr("guests.models.Guest", SimpleNamespace(objects=_Chain(first_result=guest)))
    monkeypatch.setattr(
        "guests.services.training.finalize_guest_training",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("training backend unavailable")),
    )
    monkeypatch.setattr(
        guest_tasks.complete_guest_training,
        "retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )

    with pytest.raises(RuntimeError, match="training backend unavailable"):
        guest_tasks.complete_guest_training.run(103)


@pytest.mark.django_db
def test_scan_guest_training_programming_error_bubbles_up(monkeypatch):
    import guests.tasks as guest_tasks

    now = timezone.now()
    guests = [SimpleNamespace(id=1)]

    monkeypatch.setattr(
        "guests.models.Guest",
        SimpleNamespace(objects=_Chain(slice_result=guests)),
    )
    monkeypatch.setattr("guests.tasks.timezone.now", lambda: now)
    monkeypatch.setattr(
        "guests.services.training.finalize_guest_training",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken guest training scan contract")),
    )

    with pytest.raises(AssertionError, match="broken guest training scan contract"):
        guest_tasks.scan_guest_training()


@pytest.mark.django_db
def test_complete_guest_recruitment_programming_error_bubbles_without_retry(monkeypatch):
    import guests.tasks as guest_tasks

    now = timezone.now()
    recruitment = SimpleNamespace(complete_at=now - timedelta(seconds=1), id=201)
    monkeypatch.setattr(
        "guests.models.GuestRecruitment",
        SimpleNamespace(objects=_Chain(first_result=recruitment)),
    )
    monkeypatch.setattr("guests.tasks.timezone.now", lambda: now)
    monkeypatch.setattr(
        guest_tasks.complete_guest_recruitment,
        "retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not be called")),
    )
    monkeypatch.setattr(
        "guests.services.recruitment.finalize_guest_recruitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken guest recruitment finalize contract")),
    )

    with pytest.raises(AssertionError, match="broken guest recruitment finalize contract"):
        guest_tasks.complete_guest_recruitment.run(201)


@pytest.mark.django_db
def test_scan_guest_recruitments_programming_error_bubbles_up(monkeypatch):
    import guests.tasks as guest_tasks

    now = timezone.now()
    recruitments = [SimpleNamespace(id=1)]

    class _Status:
        PENDING = "pending"

    monkeypatch.setattr(
        "guests.models.GuestRecruitment",
        SimpleNamespace(objects=_Chain(slice_result=recruitments), Status=_Status),
    )
    monkeypatch.setattr("guests.tasks.timezone.now", lambda: now)
    monkeypatch.setattr(
        "guests.services.recruitment.finalize_guest_recruitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken guest recruitment scan contract")),
    )

    with pytest.raises(AssertionError, match="broken guest recruitment scan contract"):
        guest_tasks.scan_guest_recruitments()


@pytest.mark.django_db
def test_guest_training_via_safe_apply_async(monkeypatch):
    import guests.services.training as guest_training_service
    import guests.tasks as guest_tasks

    called = {}

    def _safe_apply_async(task, *, args=None, countdown=None, logger=None, log_message="", **_kwargs):
        called["task"] = task
        called["args"] = args
        called["countdown"] = countdown
        called["logger"] = logger
        called["log_message"] = log_message
        return True

    def _apply_async_should_not_run(*_args, **_kwargs):
        raise AssertionError("direct apply_async should not be used")

    monkeypatch.setattr(guest_training_service, "safe_apply_async", _safe_apply_async)
    monkeypatch.setattr(guest_tasks.complete_guest_training, "apply_async", _apply_async_should_not_run)

    guest_training_service._try_enqueue_complete_guest_training(
        SimpleNamespace(id=77, training_complete_at=timezone.now()),
        countdown=5,
        source="test",
    )

    assert called["task"] is guest_tasks.complete_guest_training
    assert called["args"] == [77]
    assert called["countdown"] == 5
    assert called["logger"] is guest_training_service.logger
    assert called["log_message"] == "guest training task dispatch failed"


def test_guest_training_missing_target_module_degrades(monkeypatch):
    from django.conf import settings

    import guests.services.training as guest_training_service

    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "guests.tasks":
            exc = ModuleNotFoundError("No module named 'guests.tasks'")
            exc.name = "guests.tasks"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(
        guest_training_service,
        "finalize_guest_training",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not finalize training")),
    )
    monkeypatch.setattr(
        guest_training_service,
        "safe_apply_async",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not dispatch training task")),
    )

    guest_training_service._try_enqueue_complete_guest_training(
        SimpleNamespace(id=78, training_complete_at=timezone.now()),
        countdown=5,
        source="test-missing-target",
    )


def test_guest_training_unexpected_import_error_bubbles_up(monkeypatch):
    import guests.services.training as guest_training_service

    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "guests.tasks":
            raise RuntimeError("broken task module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(RuntimeError, match="broken task module"):
        guest_training_service._try_enqueue_complete_guest_training(
            SimpleNamespace(id=79, training_complete_at=timezone.now()),
            countdown=5,
            source="test-broken-import",
        )


def test_guest_training_nested_import_error_bubbles_up(monkeypatch):
    import guests.services.training as guest_training_service

    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "guests.tasks":
            exc = ModuleNotFoundError("No module named 'redis'")
            exc.name = "redis"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        guest_training_service._try_enqueue_complete_guest_training(
            SimpleNamespace(id=80, training_complete_at=timezone.now()),
            countdown=5,
            source="test-nested-import",
        )
