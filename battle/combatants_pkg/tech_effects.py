"""
Tech effects builder for combat units.
"""
from __future__ import annotations

from typing import Dict


def build_tech_effects(
    troop_class: str,
    tech_levels: Dict[str, int],
) -> Dict[str, float]:
    """
    Build tech effects for a troop class.

    Args:
        troop_class: Troop class (dao/qiang/jian/quan/gong)
        tech_levels: Technology levels dict

    Returns:
        Special effect parameters dict
    """
    from core.game_data.technology import get_tech_bonus_from_levels

    effects: Dict[str, float] = {}

    def _bonus(effect: str) -> float:
        return get_tech_bonus_from_levels(tech_levels, effect, troop_class)

    if troop_class == "dao":
        double_strike = _bonus("double_strike_chance")
        if double_strike > 0:
            effects["double_strike_chance"] = double_strike

    elif troop_class == "qiang":
        counter = _bonus("counter_attack_chance")
        if counter > 0:
            effects["counter_attack_chance"] = counter
            effects["counter_attack_damage"] = 0.30

    elif troop_class == "jian":
        reflect = _bonus("damage_reflect")
        if reflect > 0:
            effects["damage_reflect"] = 0.10 + reflect
        preempt = _bonus("preemptive_strike")
        if preempt > 0:
            effects["preemptive_damage"] = 0.50 + preempt

    elif troop_class == "quan":
        ranged_def = _bonus("ranged_defense")
        if ranged_def > 0:
            effects["ranged_defense"] = ranged_def
        heal = _bonus("battle_heal_chance")
        if heal > 0:
            effects["battle_heal_chance"] = heal
            effects["battle_heal_amount"] = 0.10

    elif troop_class == "gong":
        extra_range = _bonus("extra_range")
        if extra_range > 0:
            effects["extra_range_damage"] = 0.35 + extra_range
        melee = _bonus("melee_attack")
        if melee > 0:
            effects["melee_attack_bonus"] = melee

    return effects
