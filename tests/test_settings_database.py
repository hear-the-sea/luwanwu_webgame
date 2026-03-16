from __future__ import annotations

import pytest

from config.settings import database as database_settings


def test_redis_url_has_auth_detects_credentials():
    assert database_settings._redis_url_has_auth("redis://:secret@127.0.0.1:6379/0") is True
    assert database_settings._redis_url_has_auth("redis://127.0.0.1:6379/0") is False


def test_validate_production_infrastructure_rejects_sqlite_in_strict_mode():
    with pytest.raises(RuntimeError, match="non-SQLite"):
        database_settings._validate_production_infrastructure(
            strict_mode=True,
            db_engine="django.db.backends.sqlite3",
            db_name="/tmp/test.sqlite3",
            redis_password="secret",
            redis_urls=("redis://:secret@127.0.0.1:6379/0",),
        )


def test_validate_production_infrastructure_rejects_unauthenticated_redis():
    with pytest.raises(RuntimeError, match="authenticated Redis"):
        database_settings._validate_production_infrastructure(
            strict_mode=True,
            db_engine="django.db.backends.mysql",
            db_name="webgame",
            redis_password="",
            redis_urls=("redis://127.0.0.1:6379/0",),
        )


def test_validate_production_infrastructure_allows_authenticated_non_sqlite_stack():
    database_settings._validate_production_infrastructure(
        strict_mode=True,
        db_engine="django.db.backends.mysql",
        db_name="webgame",
        redis_password="secret",
        redis_urls=("redis://127.0.0.1:6379/0",),
    )
