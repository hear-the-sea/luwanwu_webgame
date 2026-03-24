from __future__ import annotations

import pytest

from core.utils.yaml_schema import ValidationResult


def assert_valid(result: ValidationResult) -> None:
    __tracebackhide__ = True
    if not result.is_valid:
        lines = [str(error) for error in result.errors]
        pytest.fail(f"Expected valid, got {len(lines)} error(s):\n" + "\n".join(lines))


def assert_has_error(result: ValidationResult, *, substring: str) -> None:
    __tracebackhide__ = True
    assert not result.is_valid, "Expected errors but result was valid"
    messages = [str(error) for error in result.errors]
    if not any(substring in message for message in messages):
        pytest.fail(f"No error containing '{substring}'. Errors:\n" + "\n".join(messages))
