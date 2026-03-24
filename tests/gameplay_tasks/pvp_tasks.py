from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

import gameplay.tasks as tasks
from tests.gameplay_tasks.support import Chain


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
        SimpleNamespace(objects=Chain(first_result=record), Status=_Status),
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
        SimpleNamespace(objects=Chain(first_result=run), Status=_Status),
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
