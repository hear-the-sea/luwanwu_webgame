"""
Guest combatant builder.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.db import DatabaseError

from guests.models import Guest, Skill, SkillKind

from .core import Combatant

logger = logging.getLogger(__name__)

# Guest combat constants
DEFAULT_GUEST_AGILITY = 80
INTELLECT_TO_SPEED_DIVISOR = 10
MIN_SPEED_BONUS = 5
DEFAULT_LUCK = 50
VANGUARD_RATIO = 0.25

# Import from parent module to avoid circular imports
MAX_SQUAD = 5  # Will be overridden by constants import


def _get_max_squad() -> int:
    """Get MAX_SQUAD from constants, with fallback."""
    try:
        from battle.constants import MAX_SQUAD as SQUAD
        return SQUAD
    except ImportError:
        return 5


def serialize_skills(guest: Guest, override_skill_keys: Optional[List[str]] = None) -> List[dict]:
    """
    Serialize guest skills to battle system format.

    Args:
        guest: Guest instance
        override_skill_keys: Optional skill key list to override guest's skills

    Returns:
        List of skill dicts
    """
    data: List[dict] = []

    guest_override_skills = getattr(guest, "_override_skills", None)
    effective_override = guest_override_skills if guest_override_skills is not None else override_skill_keys

    if effective_override:
        try:
            override_keys = [effective_override] if isinstance(effective_override, str) else list(effective_override)
        except TypeError:
            logger.warning(
                "Invalid override skills type; falling back to default skills",
                extra={
                    "guest_id": getattr(guest, "pk", None),
                    "override_skills_type": type(effective_override).__name__,
                },
            )
            override_keys = []

        override_keys = [str(key) for key in override_keys if key]
        if override_keys:
            try:
                skills = Skill.objects.filter(key__in=override_keys)
                for skill in skills:
                    data.append(
                        {
                            "key": skill.key,
                            "name": skill.name,
                            "power": skill.base_power,
                            "probability": skill.base_probability,
                            "kind": getattr(skill, "kind", SkillKind.ACTIVE),
                            "status_effect": getattr(skill, "status_effect", ""),
                            "status_probability": getattr(skill, "status_probability", 0.0),
                            "status_duration": getattr(skill, "status_duration", 1),
                            "damage_formula": getattr(skill, "damage_formula", {}),
                            "targets": getattr(skill, "targets", 1),
                        }
                    )
                return data
            except DatabaseError:
                logger.warning(
                    "Failed to load override skills for guest; falling back to default skills",
                    extra={
                        "guest_id": getattr(guest, "pk", None),
                        "override_skills_count": len(override_keys),
                    },
                    exc_info=True,
                )

    if getattr(guest, "pk", None) is not None:
        if hasattr(guest, "skills"):
            try:
                skills_qs = guest.skills.all()
                for skill in skills_qs:
                    data.append(
                        {
                            "key": skill.key,
                            "name": skill.name,
                            "power": skill.base_power,
                            "probability": skill.base_probability,
                            "kind": getattr(skill, "kind", SkillKind.ACTIVE),
                            "status_effect": getattr(skill, "status_effect", ""),
                            "status_probability": getattr(skill, "status_probability", 0.0),
                            "status_duration": getattr(skill, "status_duration", 1),
                            "damage_formula": getattr(skill, "damage_formula", {}),
                            "targets": getattr(skill, "targets", 1),
                        }
                    )
            except ValueError:
                pass
    else:
        template = getattr(guest, "template", None)
        if template and hasattr(template, "initial_skills"):
            try:
                skills_qs = template.initial_skills.all()
                for skill in skills_qs:
                    data.append(
                        {
                            "key": skill.key,
                            "name": skill.name,
                            "power": skill.base_power,
                            "probability": skill.base_probability,
                            "kind": getattr(skill, "kind", SkillKind.ACTIVE),
                            "status_effect": getattr(skill, "status_effect", ""),
                            "status_probability": getattr(skill, "status_probability", 0.0),
                            "status_duration": getattr(skill, "status_duration", 1),
                            "damage_formula": getattr(skill, "damage_formula", {}),
                            "targets": getattr(skill, "targets", 1),
                        }
                    )
            except DatabaseError:
                logger.warning(
                    "Failed to load template skills for AI guest",
                    extra={"guest_template": getattr(template, "key", None)},
                    exc_info=True,
                )

    return data


def serialize_guest_for_report(combatant: Combatant) -> Dict[str, Any]:
    return {
        "name": combatant.name,
        "attack": combatant.attack,
        "defense": combatant.defense,
        "hp": combatant.max_hp,
        "max_hp": combatant.max_hp,
        "initial_hp": combatant.initial_hp or combatant.max_hp,
        "remaining_hp": max(0, combatant.hp),
        "rarity": combatant.rarity,
        "priority": combatant.priority,
        "template_key": combatant.template_key,
        "guest_id": combatant.guest_id,
        "level": combatant.level,
    }


def build_guest_combatants(
    guests: List[Guest],
    side: str,
    limit: int | None = None,
    stat_bonuses: Optional[Dict[str, float]] = None,
    override_skill_keys: Optional[List[str]] = None,
) -> List[Combatant]:
    """
    Build guest combatant list.

    Args:
        guests: Guest list
        side: Side ("attacker" or "defender")
        limit: Max guest count
        stat_bonuses: Stat bonus dict {"attack": 0.3, ...}
        override_skill_keys: Temp skill list (overrides guest's skills)

    Returns:
        Combatant list
    """
    team: List[Combatant] = []
    use_limit = limit if limit is not None else _get_max_squad()

    MAX_STAT_VALUE = 999999

    for guest in guests[:use_limit]:
        stats = guest.stat_block()

        bonuses = stat_bonuses or {}
        attack_mult = 1.0 + bonuses.get("attack", 0)
        defense_mult = 1.0 + bonuses.get("defense", 0)
        hp_mult = 1.0 + bonuses.get("hp", 0)
        agility_mult = 1.0 + bonuses.get("agility", 0)

        attack = min(MAX_STAT_VALUE, int(stats["attack"] * attack_mult))
        defense = min(MAX_STAT_VALUE, int(stats["defense"] * defense_mult))
        max_hp = min(MAX_STAT_VALUE, int(stats["hp"] * hp_mult))

        if getattr(guest, "pk", None) is not None:
            raw_current_hp = getattr(guest, "current_hp", 0) or 0
            hp = min(max_hp, int(raw_current_hp * hp_mult))
            hp = max(1, hp)
        else:
            hp = max_hp

        base_agility = getattr(guest, "agility", DEFAULT_GUEST_AGILITY)
        intellect_value = stats.get(
            "intellect", getattr(guest, "intellect", DEFAULT_GUEST_AGILITY)
        )
        troop_speed = max(MIN_SPEED_BONUS, intellect_value // INTELLECT_TO_SPEED_DIVISOR)
        agility = int((base_agility + troop_speed) * agility_mult)

        priority = 0
        team.append(
            Combatant(
                name=guest.display_name,
                guest_id=getattr(guest, "id", None),
                attack=attack,
                defense=defense,
                hp=hp,
                max_hp=max_hp,
                side=side,
                rarity=guest.rarity,
                luck=getattr(guest, "luck", DEFAULT_LUCK),
                agility=agility,
                priority=priority,
                kind="guest",
                troop_strength=0,
                initial_hp=hp,
                template_key=guest.template.key,
                skills=serialize_skills(guest, override_skill_keys=override_skill_keys),
                force_attr=getattr(guest, "force", 100),
                intellect_attr=getattr(guest, "intellect", 100),
                defense_attr=getattr(guest, "defense_stat", stats["defense"]),
                level=getattr(guest, "level", 1),
            )
        )
    return team


def assign_agility_based_priorities(
    attacker_units: List[Combatant],
    defender_units: List[Combatant],
) -> None:
    """
    Dynamically assign priorities based on agility distribution.

    Rules:
    - Top 25% fastest guests -> priority -1 (vanguard, round 1)
    - Remaining 75% guests -> priority 0 (main force, round 2)
    """
    all_units = attacker_units + defender_units
    guests = [u for u in all_units if u.kind == "guest"]

    if not guests:
        return

    sorted_guests = sorted(guests, key=lambda g: g.agility, reverse=True)
    total = len(sorted_guests)

    cutoff = max(1, int(total * VANGUARD_RATIO))

    for idx, guest in enumerate(sorted_guests):
        if idx < cutoff:
            guest.priority = -1
        else:
            guest.priority = 0
