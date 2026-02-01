from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Dict, Optional

import yaml
from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_technology_templates() -> Dict[str, Any]:
    """
    Load technology templates from YAML.

    Kept in core to allow multiple apps (battle/gameplay/...) to share the same
    read-only calculations without creating cross-app import cycles.
    """
    path = os.path.join(settings.BASE_DIR, "data", "technology_templates.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("technology_templates.yaml not found: %s", path)
        return {}
    except Exception:
        logger.exception("Failed to load technology templates from %s", path)
        return {}


@lru_cache(maxsize=1)
def _build_troop_to_class_index() -> Dict[str, str]:
    data = load_technology_templates()
    index: Dict[str, str] = {}
    for class_key, class_info in (data.get("troop_classes") or {}).items():
        for troop_key in class_info.get("troops", []) or []:
            index[str(troop_key)] = str(class_key)
    return index


def get_troop_class_for_key(troop_key: str) -> Optional[str]:
    """Return troop class key for a troop key (e.g. dao_ke -> dao)."""
    return _build_troop_to_class_index().get(troop_key)


def get_tech_bonus_from_levels(levels: Dict[str, int], effect_type: str, troop_class: Optional[str] = None) -> float:
    """
    Pure data technology bonus calculation (used for AI/enemy/preview).

    Returns a multiplier (e.g. 0.3 means +30%).
    """
    data = load_technology_templates()
    total = 0.0
    for tech in data.get("technologies", []) or []:
        if tech.get("effect_type") != effect_type:
            continue
        tech_troop_class = tech.get("troop_class")
        if tech_troop_class and troop_class and tech_troop_class != troop_class:
            continue
        level = int(levels.get(tech["key"], 0) or 0)
        if level <= 0:
            continue
        effect_per_level = tech.get("effect_per_level", 0.10)
        total += level * effect_per_level
    return total


def get_troop_stat_bonuses_from_levels(levels: Dict[str, int], troop_key: str) -> Dict[str, float]:
    """Return per-stat bonus multipliers for a troop key based on provided tech levels."""
    troop_class = get_troop_class_for_key(troop_key)
    if not troop_class:
        return {}

    bonuses: Dict[str, float] = {}
    for effect_type, stat_key in [
        ("troop_attack", "attack"),
        ("troop_defense", "defense"),
        ("troop_agility", "agility"),
        ("troop_hp", "hp"),
    ]:
        bonus = get_tech_bonus_from_levels(levels, effect_type, troop_class)
        if bonus > 0:
            bonuses[stat_key] = bonus
    return bonuses


def build_uniform_tech_levels(level: int) -> Dict[str, int]:
    """Map a single level to all technology keys, clamped by each tech's max_level."""
    data = load_technology_templates()
    resolved: Dict[str, int] = {}
    for tech in data.get("technologies", []) or []:
        max_level = int(tech.get("max_level", level) or level)
        resolved[tech["key"]] = max(0, min(int(level or 0), max_level))
    return resolved


def resolve_enemy_tech_levels(config: Dict[str, Any]) -> Dict[str, int]:
    """
    Merge rules:
    1) config.level sets a uniform baseline; 2) config.levels overrides per key.
    """
    if not config:
        return {}
    levels: Dict[str, int] = {}
    if config.get("level") is not None:
        levels = build_uniform_tech_levels(int(config.get("level", 0)))
    for key, val in (config.get("levels") or {}).items():
        levels[str(key)] = int(val)
    return levels


def get_guest_stat_bonuses(config: Dict[str, Any]) -> Dict[str, float]:
    """
    Compute guest stat bonuses from config.

    Currently supports:
    - guest_bonus: uniform percent bonus (e.g. 0.2 means +20%), agility is half.
    """
    if not config:
        return {}

    bonuses: Dict[str, float] = {}
    if "guest_bonus" in config:
        bonus_percent = float(config.get("guest_bonus", 0))
        bonuses["attack"] = bonus_percent
        bonuses["defense"] = bonus_percent
        bonuses["hp"] = bonus_percent
        bonuses["agility"] = bonus_percent * 0.5
    return bonuses


def clear_technology_cache() -> None:
    """Clear YAML caches (useful for tests or runtime reload)."""
    load_technology_templates.cache_clear()
    _build_troop_to_class_index.cache_clear()
