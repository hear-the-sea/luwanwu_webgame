from __future__ import annotations


def assert_invalid(result, *, substring: str | None = None) -> None:
    assert not result.is_valid
    if substring is not None:
        assert any(substring in error.message for error in result.errors)
