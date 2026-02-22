from __future__ import annotations

from gameplay.selectors.home import _normalize_hourly_rates


def test_normalize_hourly_rates_coerces_invalid_values():
    normalized = _normalize_hourly_rates(
        {
            "grain": "120",
            "silver": "invalid",
            "stone": None,
            "wood": -8,
            "iron": 3.8,
            123: 456,
        }
    )

    assert normalized == {
        "grain": 120,
        "silver": 0,
        "stone": 0,
        "wood": 0,
        "iron": 3,
    }


def test_normalize_hourly_rates_rejects_non_mapping_input():
    assert _normalize_hourly_rates(None) == {}
    assert _normalize_hourly_rates("bad") == {}
