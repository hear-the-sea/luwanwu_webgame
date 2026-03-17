"""Compatibility wrappers for the guest growth engine."""

from __future__ import annotations

from ..growth_engine import allocate_level_up_attributes, apply_attribute_growth, get_expected_growth
from ..growth_rules import CIVIL_ATTRIBUTE_WEIGHTS, MILITARY_ATTRIBUTE_WEIGHTS, RARITY_ATTRIBUTE_GROWTH_RANGE

__all__ = [
    "CIVIL_ATTRIBUTE_WEIGHTS",
    "MILITARY_ATTRIBUTE_WEIGHTS",
    "RARITY_ATTRIBUTE_GROWTH_RANGE",
    "allocate_level_up_attributes",
    "apply_attribute_growth",
    "get_expected_growth",
]
