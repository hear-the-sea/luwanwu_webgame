from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from gameplay.services.manor import refresh as manor_refresh


class _FakeQuerySet:
    def __init__(self, *, exists_result: bool = False):
        self.exists_result = exists_result
        self.exists_calls = 0

    def filter(self, *_args, **_kwargs):
        return self

    def exists(self):
        self.exists_calls += 1
        return self.exists_result


class _FakeManager:
    def __init__(self, queryset: _FakeQuerySet):
        self.queryset = queryset

    def filter(self, *_args, **_kwargs):
        return self.queryset


class _FakeModel:
    def __init__(self, queryset: _FakeQuerySet, status: SimpleNamespace):
        self.objects = _FakeManager(queryset)
        self.Status = status


def test_has_due_manor_refresh_work_collapses_to_three_exists_checks():
    mission_qs = _FakeQuerySet()
    scout_qs = _FakeQuerySet()
    raid_qs = _FakeQuerySet()

    mission_model = _FakeModel(mission_qs, SimpleNamespace(ACTIVE="active"))
    scout_model = _FakeModel(scout_qs, SimpleNamespace(SCOUTING="scouting", RETURNING="returning"))
    raid_model = _FakeModel(raid_qs, SimpleNamespace(MARCHING="marching", RETURNING="returning", RETREATED="retreated"))

    result = manor_refresh.has_due_manor_refresh_work(
        mission_run_model=mission_model,
        scout_record_model=scout_model,
        raid_run_model=raid_model,
        manor_id=1,
        now=object(),
        logger=MagicMock(),
    )

    assert result is False
    assert mission_qs.exists_calls == 1
    assert scout_qs.exists_calls == 1
    assert raid_qs.exists_calls == 1
