from __future__ import annotations

from config.settings import base as base_settings


def test_production_default_flag_enables_strict_defaults_only_outside_debug_and_tests():
    assert base_settings._production_default_flag(debug=False, running_tests=False) == "1"
    assert base_settings._production_default_flag(debug=True, running_tests=False) == "0"
    assert base_settings._production_default_flag(debug=False, running_tests=True) == "0"
