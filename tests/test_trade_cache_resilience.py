from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.db import DatabaseError

from trade.services.cache_resilience import (
    best_effort_cache_add,
    best_effort_cache_delete,
    best_effort_cache_get,
    best_effort_cache_set,
    strict_cache_add,
    strict_cache_get,
)


def test_strict_cache_get_wraps_infrastructure_error():
    cache_backend = MagicMock()
    cache_backend.get.side_effect = DatabaseError("db down")
    logger = MagicMock()

    with pytest.raises(RuntimeError, match="cache unavailable"):
        strict_cache_get(
            cache_backend,
            "k",
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
            unavailable_error_factory=lambda: RuntimeError("cache unavailable"),
        )

    logger.error.assert_called_once()


def test_strict_cache_get_programming_error_bubbles_up_without_extra_logging():
    cache_backend = MagicMock()
    cache_backend.get.side_effect = AssertionError("broken cache contract")
    logger = MagicMock()

    with pytest.raises(AssertionError, match="broken cache contract"):
        strict_cache_get(
            cache_backend,
            "k",
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
            unavailable_error_factory=lambda: RuntimeError("cache unavailable"),
        )

    logger.error.assert_not_called()


def test_strict_cache_add_wraps_infrastructure_error():
    cache_backend = MagicMock()
    cache_backend.add.side_effect = DatabaseError("db down")
    logger = MagicMock()

    with pytest.raises(RuntimeError, match="cache unavailable"):
        strict_cache_add(
            cache_backend,
            "k",
            "v",
            timeout=30,
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
            unavailable_error_factory=lambda: RuntimeError("cache unavailable"),
        )

    logger.error.assert_called_once()


def test_strict_cache_add_programming_error_bubbles_up_without_extra_logging():
    cache_backend = MagicMock()
    cache_backend.add.side_effect = AssertionError("broken cache contract")
    logger = MagicMock()

    with pytest.raises(AssertionError, match="broken cache contract"):
        strict_cache_add(
            cache_backend,
            "k",
            "v",
            timeout=30,
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
            unavailable_error_factory=lambda: RuntimeError("cache unavailable"),
        )

    logger.error.assert_not_called()


def test_best_effort_cache_get_returns_default_on_infrastructure_error():
    cache_backend = MagicMock()
    cache_backend.get.side_effect = DatabaseError("db down")
    logger = MagicMock()

    result = best_effort_cache_get(
        cache_backend,
        "k",
        default="fallback",
        logger=logger,
        component="test_cache",
        infrastructure_exceptions=(DatabaseError,),
    )

    assert result == "fallback"
    logger.warning.assert_called_once()


def test_best_effort_cache_get_programming_error_bubbles_up():
    cache_backend = MagicMock()
    cache_backend.get.side_effect = AssertionError("broken cache contract")
    logger = MagicMock()

    with pytest.raises(AssertionError, match="broken cache contract"):
        best_effort_cache_get(
            cache_backend,
            "k",
            default="fallback",
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
        )

    logger.warning.assert_not_called()


def test_best_effort_cache_set_ignores_infrastructure_error():
    cache_backend = MagicMock()
    cache_backend.set.side_effect = DatabaseError("db down")
    logger = MagicMock()

    best_effort_cache_set(
        cache_backend,
        "k",
        "v",
        timeout=30,
        logger=logger,
        component="test_cache",
        infrastructure_exceptions=(DatabaseError,),
    )

    logger.warning.assert_called_once()


def test_best_effort_cache_set_programming_error_bubbles_up():
    cache_backend = MagicMock()
    cache_backend.set.side_effect = AssertionError("broken cache contract")
    logger = MagicMock()

    with pytest.raises(AssertionError, match="broken cache contract"):
        best_effort_cache_set(
            cache_backend,
            "k",
            "v",
            timeout=30,
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
        )

    logger.warning.assert_not_called()


def test_best_effort_cache_add_returns_false_on_infrastructure_error():
    cache_backend = MagicMock()
    cache_backend.add.side_effect = DatabaseError("db down")
    logger = MagicMock()

    result = best_effort_cache_add(
        cache_backend,
        "k",
        "v",
        timeout=30,
        logger=logger,
        component="test_cache",
        infrastructure_exceptions=(DatabaseError,),
    )

    assert result is False
    logger.warning.assert_called_once()


def test_best_effort_cache_add_programming_error_bubbles_up():
    cache_backend = MagicMock()
    cache_backend.add.side_effect = AssertionError("broken cache contract")
    logger = MagicMock()

    with pytest.raises(AssertionError, match="broken cache contract"):
        best_effort_cache_add(
            cache_backend,
            "k",
            "v",
            timeout=30,
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
        )

    logger.warning.assert_not_called()


def test_best_effort_cache_delete_ignores_infrastructure_error():
    cache_backend = MagicMock()
    cache_backend.delete.side_effect = DatabaseError("db down")
    logger = MagicMock()

    best_effort_cache_delete(
        cache_backend,
        "k",
        logger=logger,
        component="test_cache",
        infrastructure_exceptions=(DatabaseError,),
    )

    logger.warning.assert_called_once()


def test_best_effort_cache_delete_programming_error_bubbles_up():
    cache_backend = MagicMock()
    cache_backend.delete.side_effect = AssertionError("broken cache contract")
    logger = MagicMock()

    with pytest.raises(AssertionError, match="broken cache contract"):
        best_effort_cache_delete(
            cache_backend,
            "k",
            logger=logger,
            component="test_cache",
            infrastructure_exceptions=(DatabaseError,),
        )

    logger.warning.assert_not_called()
