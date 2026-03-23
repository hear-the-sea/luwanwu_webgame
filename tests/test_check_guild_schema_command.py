from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import DatabaseError

from guilds.management.commands.check_guild_schema import _actual_columns_for_table


class _CursorContext:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_actual_columns_for_table_returns_none_on_database_error(monkeypatch):
    monkeypatch.setattr("guilds.management.commands.check_guild_schema.connection.cursor", lambda: _CursorContext())
    monkeypatch.setattr(
        "guilds.management.commands.check_guild_schema.connection.introspection.get_table_description",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    assert _actual_columns_for_table("guild_members") is None


def test_actual_columns_for_table_programming_error_bubbles_up(monkeypatch):
    monkeypatch.setattr("guilds.management.commands.check_guild_schema.connection.cursor", lambda: _CursorContext())
    monkeypatch.setattr(
        "guilds.management.commands.check_guild_schema.connection.introspection.get_table_description",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("broken introspection contract")),
    )

    with pytest.raises(AssertionError, match="broken introspection contract"):
        _actual_columns_for_table("guild_members")


def test_actual_columns_for_table_returns_column_names(monkeypatch):
    monkeypatch.setattr("guilds.management.commands.check_guild_schema.connection.cursor", lambda: _CursorContext())
    monkeypatch.setattr(
        "guilds.management.commands.check_guild_schema.connection.introspection.get_table_description",
        lambda *_a, **_k: [SimpleNamespace(name="id"), SimpleNamespace(name="guild_id")],
    )

    assert _actual_columns_for_table("guild_members") == {"id", "guild_id"}
