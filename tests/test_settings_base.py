from __future__ import annotations

import pytest

from config.settings import base as base_settings


@pytest.mark.parametrize(
    ("raw_value", "default", "expected"),
    [
        ("0.75", 0.5, 0.75),
        ("", 0.5, 0.5),
        ("not-a-number", 0.5, 0.5),
        ("inf", 0.5, 0.5),
    ],
)
def test_env_float_parsing(monkeypatch: pytest.MonkeyPatch, raw_value: str, default: float, expected: float):
    monkeypatch.setenv("TEST_FLOAT_ENV", raw_value)

    assert base_settings.env_float("TEST_FLOAT_ENV", default) == expected


def test_single_session_fail_open_defaults_to_true():
    assert base_settings.SINGLE_SESSION_FAIL_OPEN is True
