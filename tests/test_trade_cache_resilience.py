from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.db import DatabaseError

from trade.services.cache_resilience import strict_cache_add, strict_cache_get


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
