from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import DatabaseError

from gameplay.views.read_helpers import prepare_manor_for_read


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
