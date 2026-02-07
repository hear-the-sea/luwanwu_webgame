"""
Backward compatibility shim for battle.combatants module.

All functionality has been moved to battle.combatants_pkg package.
This module re-exports everything for backward compatibility.
"""
from __future__ import annotations

# Re-export everything from the new package
from .combatants_pkg import (
    # Core data classes
    BattleSimulationResult,
    Combatant,
    # Cache management
    clear_guest_template_cache,
    get_all_guest_templates,
    # Tech effects
    build_tech_effects,
    # Guest builder
    DEFAULT_GUEST_AGILITY,
    DEFAULT_LUCK,
    INTELLECT_TO_SPEED_DIVISOR,
    MIN_SPEED_BONUS,
    VANGUARD_RATIO,
    assign_agility_based_priorities,
    build_guest_combatants,
    serialize_guest_for_report,
    serialize_skills,
    # Troop builder
    build_troop_combatants,
    normalize_troop_loadout,
    # AI generator
    allocate_ai_attribute_points,
    build_ai_guests,
    build_named_ai_guests,
    generate_ai_loadout,
)

# Backward compatibility aliases
_get_all_guest_templates = get_all_guest_templates
_allocate_ai_attribute_points = allocate_ai_attribute_points
_build_tech_effects = build_tech_effects

# Re-export cache constants for backward compatibility
GUEST_TEMPLATE_CACHE_KEY = "battle:guest_templates"
GUEST_TEMPLATE_CACHE_TTL = 300

__all__ = [
    # Core
    "BattleSimulationResult",
    "Combatant",
    # Cache
    "clear_guest_template_cache",
    "GUEST_TEMPLATE_CACHE_KEY",
    "GUEST_TEMPLATE_CACHE_TTL",
    # Tech effects
    "build_tech_effects",
    # Guest builder
    "DEFAULT_GUEST_AGILITY",
    "DEFAULT_LUCK",
    "INTELLECT_TO_SPEED_DIVISOR",
    "MIN_SPEED_BONUS",
    "VANGUARD_RATIO",
    "assign_agility_based_priorities",
    "build_guest_combatants",
    "serialize_guest_for_report",
    "serialize_skills",
    # Troop builder
    "build_troop_combatants",
    "normalize_troop_loadout",
    # AI generator
    "build_ai_guests",
    "build_named_ai_guests",
    "generate_ai_loadout",
    # Backward compatibility (private functions)
    "_get_all_guest_templates",
    "_allocate_ai_attribute_points",
    "_build_tech_effects",
]
