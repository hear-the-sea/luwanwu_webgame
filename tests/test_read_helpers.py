from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import DatabaseError

from gameplay.views.read_helpers import (
    get_prepared_manor_for_read,
    get_prepared_manor_with_raid_activity_for_read,
    prepare_manor_activity_for_read,
    prepare_manor_for_read,
    prepare_raid_activity_for_read,
)


def test_prepare_manor_for_read_degrades_database_error():
    logger = MagicMock()
    failures: list[str] = []

    result = prepare_manor_for_read(
        SimpleNamespace(id=1),
        project_fn=lambda _manor: (_ for _ in ()).throw(DatabaseError("db down")),
        logger=logger,
        source="unit-test",
        on_expected_failure=lambda exc: failures.append(str(exc)),
    )

    assert result is False
    assert failures == ["db down"]
    logger.warning.assert_called_once()


def test_prepare_manor_for_read_does_not_swallow_runtime_keyword_guess():
    logger = MagicMock()

    with pytest.raises(RuntimeError, match="cache backend unavailable"):
        prepare_manor_for_read(
            SimpleNamespace(id=1),
            project_fn=lambda _manor: (_ for _ in ()).throw(RuntimeError("cache backend unavailable")),
            logger=logger,
            source="unit-test",
        )

    logger.warning.assert_not_called()


def test_get_prepared_manor_for_read_loads_manor_and_projects(monkeypatch):
    logger = MagicMock()
    request = SimpleNamespace(user=SimpleNamespace(id=99))
    manor = SimpleNamespace(id=7)
    calls: list[tuple[str, object]] = []

    def _fake_get_manor(user):
        calls.append(("get_manor", user))
        return manor

    def _fake_project(target_manor):
        calls.append(("project", target_manor))

    monkeypatch.setattr("gameplay.views.read_helpers.get_manor", _fake_get_manor)

    result = get_prepared_manor_for_read(
        request,
        project_fn=_fake_project,
        logger=logger,
        source="unit-test",
    )

    assert result is manor
    assert calls == [("get_manor", request.user), ("project", manor)]
    logger.warning.assert_not_called()


def test_prepare_manor_activity_for_read_degrades_expected_infrastructure_error():
    logger = MagicMock()
    failures: list[str] = []

    result = prepare_manor_activity_for_read(
        SimpleNamespace(id=1),
        refresh_fn=lambda _manor: (_ for _ in ()).throw(ConnectionError("redis down")),
        logger=logger,
        source="unit-test",
        on_expected_failure=lambda exc: failures.append(str(exc)),
    )

    assert result is False
    assert failures == ["redis down"]
    logger.warning.assert_called_once()


def test_prepare_manor_activity_for_read_raises_unexpected_error():
    logger = MagicMock()

    with pytest.raises(RuntimeError, match="boom"):
        prepare_manor_activity_for_read(
            SimpleNamespace(id=1),
            refresh_fn=lambda _manor: (_ for _ in ()).throw(RuntimeError("boom")),
            logger=logger,
            source="unit-test",
        )

    logger.warning.assert_not_called()


def test_prepare_raid_activity_for_read_refreshes_scouts_before_raids(monkeypatch):
    logger = MagicMock()
    manor = SimpleNamespace(id=7)
    calls: list[tuple[str, object, bool]] = []

    monkeypatch.setattr(
        "gameplay.views.read_helpers.refresh_scout_records",
        lambda target_manor, *, prefer_async=False: calls.append(("scout", target_manor, prefer_async)),
    )
    monkeypatch.setattr(
        "gameplay.views.read_helpers.refresh_raid_runs",
        lambda target_manor, *, prefer_async=False: calls.append(("raid", target_manor, prefer_async)),
    )

    result = prepare_raid_activity_for_read(
        manor,
        logger=logger,
        source="unit-test",
    )

    assert result is True
    assert calls == [("scout", manor, True), ("raid", manor, True)]
    logger.warning.assert_not_called()


def test_get_prepared_manor_with_raid_activity_for_read_runs_projection_then_activity(monkeypatch):
    logger = MagicMock()
    request = SimpleNamespace(user=SimpleNamespace(id=42))
    manor = SimpleNamespace(id=7)
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "gameplay.views.read_helpers.get_manor",
        lambda user: calls.append(("get_manor", user)) or manor,
    )
    monkeypatch.setattr(
        "gameplay.views.read_helpers.prepare_manor_for_read",
        lambda target_manor, **_kwargs: calls.append(("project", target_manor)) or True,
    )
    monkeypatch.setattr(
        "gameplay.views.read_helpers.prepare_raid_activity_for_read",
        lambda target_manor, **_kwargs: calls.append(("activity", target_manor)) or True,
    )

    result = get_prepared_manor_with_raid_activity_for_read(
        request,
        logger=logger,
        source="unit-test",
        project_fn=lambda _manor: None,
    )

    assert result is manor
    assert calls == [("get_manor", request.user), ("project", manor), ("activity", manor)]


def test_get_prepared_manor_with_raid_activity_for_read_allows_activity_only(monkeypatch):
    logger = MagicMock()
    request = SimpleNamespace(user=SimpleNamespace(id=24))
    manor = SimpleNamespace(id=8)
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "gameplay.views.read_helpers.get_manor",
        lambda user: calls.append(("get_manor", user)) or manor,
    )
    monkeypatch.setattr(
        "gameplay.views.read_helpers.prepare_manor_for_read",
        lambda *_args, **_kwargs: calls.append(("project", manor)) or True,
    )
    monkeypatch.setattr(
        "gameplay.views.read_helpers.prepare_raid_activity_for_read",
        lambda target_manor, **_kwargs: calls.append(("activity", target_manor)) or True,
    )

    result = get_prepared_manor_with_raid_activity_for_read(
        request,
        logger=logger,
        source="unit-test",
    )

    assert result is manor
    assert calls == [("get_manor", request.user), ("activity", manor)]
