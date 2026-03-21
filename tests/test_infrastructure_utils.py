from __future__ import annotations

from django.db import DatabaseError
from django_redis.exceptions import ConnectionInterrupted

from core.utils.infrastructure import (
    CACHE_INFRASTRUCTURE_EXCEPTIONS,
    DATABASE_INFRASTRUCTURE_EXCEPTIONS,
    is_cache_runtime_error,
    is_expected_cache_infrastructure_error,
    is_expected_infrastructure_error,
)


def test_cache_infrastructure_exceptions_include_django_redis_connection_interrupted():
    assert isinstance(ConnectionInterrupted("cache down"), CACHE_INFRASTRUCTURE_EXCEPTIONS)


def test_expected_infrastructure_error_rejects_runtime_marker_even_when_flag_enabled():
    exc = RuntimeError("cache backend unavailable")

    assert not is_expected_infrastructure_error(
        exc,
        exceptions=DATABASE_INFRASTRUCTURE_EXCEPTIONS,
        allow_runtime_markers=True,
    )


def test_expected_infrastructure_error_rejects_non_infrastructure_runtime_error():
    exc = RuntimeError("business rule broken")

    assert not is_expected_infrastructure_error(
        exc,
        exceptions=DATABASE_INFRASTRUCTURE_EXCEPTIONS,
        allow_runtime_markers=True,
    )
    assert is_cache_runtime_error(exc) is False


def test_expected_infrastructure_error_still_accepts_database_error_without_runtime_markers():
    exc = DatabaseError("db down")

    assert is_expected_infrastructure_error(exc, exceptions=DATABASE_INFRASTRUCTURE_EXCEPTIONS)


def test_expected_cache_infrastructure_error_accepts_cache_runtime_marker():
    exc = RuntimeError("cache backend unavailable")

    assert is_expected_cache_infrastructure_error(exc, exceptions=CACHE_INFRASTRUCTURE_EXCEPTIONS)


def test_cache_runtime_error_rejects_non_cache_backend_phrase():
    assert is_cache_runtime_error(RuntimeError("message backend down")) is False
    assert is_cache_runtime_error(RuntimeError("backend mismatch")) is False
    assert is_cache_runtime_error(RuntimeError("connection state invalid")) is False
    assert is_cache_runtime_error(RuntimeError("ws parser broken")) is False
