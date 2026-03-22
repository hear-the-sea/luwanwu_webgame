from __future__ import annotations

import builtins

import pytest
from django.db import DatabaseError
from django_redis.exceptions import ConnectionInterrupted

from core.utils import infrastructure as infrastructure_module
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


def test_expected_cache_infrastructure_error_rejects_cache_runtime_marker():
    exc = RuntimeError("cache backend unavailable")

    assert not is_expected_cache_infrastructure_error(exc, exceptions=CACHE_INFRASTRUCTURE_EXCEPTIONS)


def test_cache_runtime_error_rejects_non_cache_backend_phrase():
    assert is_cache_runtime_error(RuntimeError("message backend down")) is False
    assert is_cache_runtime_error(RuntimeError("backend mismatch")) is False
    assert is_cache_runtime_error(RuntimeError("connection state invalid")) is False
    assert is_cache_runtime_error(RuntimeError("ws parser broken")) is False


def test_append_optional_exception_ignores_missing_module(monkeypatch):
    captured: list[type[Exception]] = []
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "missing.test.module":
            raise ImportError("missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    infrastructure_module._append_optional_exception(
        captured,
        module_name="missing.test.module",
        attribute_name="MissingError",
    )

    assert captured == []


def test_append_optional_exception_ignores_missing_attribute(monkeypatch):
    captured: list[type[Exception]] = []
    original_import = builtins.__import__

    class _ModuleWithoutAttribute:
        pass

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "missing.test.attribute":
            return _ModuleWithoutAttribute()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    infrastructure_module._append_optional_exception(
        captured,
        module_name="missing.test.attribute",
        attribute_name="MissingError",
    )

    assert captured == []


def test_append_optional_exception_programming_error_bubbles_up(monkeypatch):
    captured: list[type[Exception]] = []
    original_import = builtins.__import__

    class _BrokenModule:
        def __getattr__(self, _name):
            raise RuntimeError("broken optional import contract")

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "broken.test.module":
            return _BrokenModule()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="broken optional import contract"):
        infrastructure_module._append_optional_exception(
            captured,
            module_name="broken.test.module",
            attribute_name="BrokenError",
        )
