"""
YAML configuration schema validation utilities.

Provides dict-based schema validators for the game's YAML config files.
No external dependencies beyond the standard library and PyYAML (already in project).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.utils.yaml_loader import load_yaml_data

logger = logging.getLogger(__name__)

SUPPORTED_YAML_CONFIGS = (
    "item_templates.yaml",
    "building_templates.yaml",
    "guest_templates.yaml",
    "troop_templates.yaml",
    "mission_templates.yaml",
    "forge_equipment.yaml",
    "shop_items.yaml",
    "arena_rules.yaml",
    "trade_market_rules.yaml",
    "warehouse_production.yaml",
    "auction_items.yaml",
    "forge_blueprints.yaml",
    "forge_decompose.yaml",
    "guest_skills.yaml",
    "recruitment_rarity_weights.yaml",
    "arena_rewards.yaml",
    "smithy_production.yaml",
    "ranch_production.yaml",
    "stable_production.yaml",
    "guild_rules.yaml",
    "guest_growth_rules.yaml",
    "technology_templates.yaml",
)


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationError:
    """A single validation error with file context."""

    file: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.file}] {self.path}: {self.message}"


@dataclass
class ValidationResult:
    """Aggregated validation result for one or more config files."""

    errors: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, file: str, path: str, message: str) -> None:
        self.errors.append(ValidationError(file=file, path=path, message=message))

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)


# ---------------------------------------------------------------------------
# Generic field-level validators
# ---------------------------------------------------------------------------


def _check_required_fields(
    entry: dict,
    required: list[str],
    *,
    result: ValidationResult,
    file: str,
    path: str,
) -> bool:
    """Return True if all required fields are present and non-None."""
    ok = True
    for field_name in required:
        if field_name not in entry or entry[field_name] is None:
            result.add(file, path, f"missing required field '{field_name}'")
            ok = False
    return ok


def _check_type(
    value: Any,
    expected_type: type | tuple[type, ...],
    *,
    result: ValidationResult,
    file: str,
    path: str,
    field_name: str,
) -> bool:
    if not isinstance(value, expected_type):
        actual = type(value).__name__
        expected = (
            expected_type.__name__ if isinstance(expected_type, type) else " | ".join(t.__name__ for t in expected_type)
        )
        result.add(file, path, f"field '{field_name}' expected {expected}, got {actual}")
        return False
    return True


def _check_in(
    value: Any,
    allowed: set | list | tuple,
    *,
    result: ValidationResult,
    file: str,
    path: str,
    field_name: str,
) -> bool:
    if value not in allowed:
        result.add(file, path, f"field '{field_name}' value '{value}' not in allowed set {sorted(allowed)}")
        return False
    return True


def _check_positive(
    value: Any,
    *,
    result: ValidationResult,
    file: str,
    path: str,
    field_name: str,
    allow_zero: bool = True,
) -> bool:
    if not isinstance(value, (int, float)):
        return True  # type check handles this separately
    lower = 0 if allow_zero else 1
    if value < lower:
        result.add(file, path, f"field '{field_name}' must be >= {lower}, got {value}")
        return False
    return True


def _check_unique_keys(
    items: list[dict],
    key_field: str,
    *,
    result: ValidationResult,
    file: str,
    context: str,
) -> None:
    """Ensure key_field values are unique across the list."""
    seen: dict[str, int] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        key = item.get(key_field)
        if key is None:
            continue
        if key in seen:
            result.add(
                file,
                f"{context}[{idx}]",
                f"duplicate {key_field} '{key}' (first seen at index {seen[key]})",
            )
        else:
            seen[key] = idx


# ---------------------------------------------------------------------------
# Schema: item_templates.yaml
# ---------------------------------------------------------------------------

VALID_ITEM_EFFECT_TYPES = {
    "resource",
    "resource_pack",
    "skill_book",
    "experience_items",
    "medicine",
    "tool",
    "loot_box",
    "equip_helmet",
    "equip_armor",
    "equip_shoes",
    "equip_weapon",
    "equip_mount",
    "equip_ornament",
    "equip_device",
}

VALID_ITEM_RARITIES = {"black", "gray", "green", "red", "blue", "purple", "orange"}


def validate_item_templates(data: dict, *, file: str = "item_templates.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    items = data.get("items")
    if items is None:
        result.add(file, "<root>", "missing required key 'items'")
        return result

    if not isinstance(items, list):
        result.add(file, "items", "expected a list")
        return result

    _check_unique_keys(items, "key", result=result, file=file, context="items")

    for idx, item in enumerate(items):
        path = f"items[{idx}]"
        if not isinstance(item, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(item, ["key", "name", "effect_type"], result=result, file=file, path=path)

        key = item.get("key")
        if key is not None:
            _check_type(key, str, result=result, file=file, path=path, field_name="key")

        effect_type = item.get("effect_type")
        if effect_type is not None:
            _check_in(
                effect_type, VALID_ITEM_EFFECT_TYPES, result=result, file=file, path=path, field_name="effect_type"
            )

        rarity = item.get("rarity")
        if rarity is not None:
            _check_in(rarity, VALID_ITEM_RARITIES, result=result, file=file, path=path, field_name="rarity")

        price = item.get("price")
        if price is not None:
            _check_type(price, (int, float), result=result, file=file, path=path, field_name="price")
            _check_positive(price, result=result, file=file, path=path, field_name="price")

        storage_space = item.get("storage_space")
        if storage_space is not None:
            _check_type(storage_space, int, result=result, file=file, path=path, field_name="storage_space")
            _check_positive(
                storage_space, result=result, file=file, path=path, field_name="storage_space", allow_zero=False
            )

        for bool_field in ("tradeable", "is_usable"):
            val = item.get(bool_field)
            if val is not None:
                _check_type(val, bool, result=result, file=file, path=path, field_name=bool_field)

    return result


# ---------------------------------------------------------------------------
# Schema: building_templates.yaml
# ---------------------------------------------------------------------------

VALID_BUILDING_CATEGORIES = {"resource", "storage", "production", "personnel", "special"}
VALID_BUILDING_RESOURCE_TYPES = {"grain", "silver"}


def validate_building_templates(data: dict, *, file: str = "building_templates.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    buildings = data.get("buildings")
    if buildings is None:
        result.add(file, "<root>", "missing required key 'buildings'")
        return result

    if not isinstance(buildings, list):
        result.add(file, "buildings", "expected a list")
        return result

    _check_unique_keys(buildings, "key", result=result, file=file, context="buildings")

    for idx, bld in enumerate(buildings):
        path = f"buildings[{idx}]"
        if not isinstance(bld, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(
            bld,
            ["key", "name", "category", "resource_type"],
            result=result,
            file=file,
            path=path,
        )

        category = bld.get("category")
        if category is not None:
            _check_in(category, VALID_BUILDING_CATEGORIES, result=result, file=file, path=path, field_name="category")

        resource_type = bld.get("resource_type")
        if resource_type is not None:
            _check_in(
                resource_type,
                VALID_BUILDING_RESOURCE_TYPES,
                result=result,
                file=file,
                path=path,
                field_name="resource_type",
            )

        for num_field in ("base_rate_per_hour", "base_upgrade_time"):
            val = bld.get(num_field)
            if val is not None:
                _check_type(val, (int, float), result=result, file=file, path=path, field_name=num_field)
                _check_positive(val, result=result, file=file, path=path, field_name=num_field)

        for float_field in ("rate_growth", "time_growth", "cost_growth"):
            val = bld.get(float_field)
            if val is not None:
                _check_type(val, (int, float), result=result, file=file, path=path, field_name=float_field)
                _check_positive(val, result=result, file=file, path=path, field_name=float_field)

        base_cost = bld.get("base_cost")
        if base_cost is not None:
            if not isinstance(base_cost, dict):
                result.add(file, path, "field 'base_cost' expected a mapping")
            else:
                for cost_key, cost_val in base_cost.items():
                    if not isinstance(cost_val, (int, float)):
                        result.add(
                            file, f"{path}.base_cost.{cost_key}", f"expected number, got {type(cost_val).__name__}"
                        )

    # Validate categories section if present
    categories = data.get("categories")
    if categories is not None:
        if not isinstance(categories, list):
            result.add(file, "categories", "expected a list")
        else:
            for idx, cat in enumerate(categories):
                cat_path = f"categories[{idx}]"
                if not isinstance(cat, dict):
                    result.add(file, cat_path, "expected a mapping")
                    continue
                _check_required_fields(cat, ["key", "name"], result=result, file=file, path=cat_path)

    return result


# ---------------------------------------------------------------------------
# Schema: guest_templates.yaml
# ---------------------------------------------------------------------------

VALID_GUEST_RARITIES = {"black", "gray", "green", "red", "blue", "purple", "orange"}
VALID_GUEST_ARCHETYPES = {"military", "civil"}


def validate_guest_templates(data: dict, *, file: str = "guest_templates.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    # Validate pools
    pools = data.get("pools")
    if pools is not None:
        if not isinstance(pools, list):
            result.add(file, "pools", "expected a list")
        else:
            _check_unique_keys(pools, "key", result=result, file=file, context="pools")
            for idx, pool in enumerate(pools):
                path = f"pools[{idx}]"
                if not isinstance(pool, dict):
                    result.add(file, path, "expected a mapping")
                    continue
                _check_required_fields(pool, ["key", "name"], result=result, file=file, path=path)

                cost = pool.get("cost")
                if cost is not None and not isinstance(cost, dict):
                    result.add(file, path, "field 'cost' expected a mapping")

                cooldown = pool.get("cooldown_seconds")
                if cooldown is not None:
                    _check_type(cooldown, int, result=result, file=file, path=path, field_name="cooldown_seconds")
                    _check_positive(cooldown, result=result, file=file, path=path, field_name="cooldown_seconds")

                draw_count = pool.get("draw_count")
                if draw_count is not None:
                    _check_type(draw_count, int, result=result, file=file, path=path, field_name="draw_count")
                    _check_positive(
                        draw_count, result=result, file=file, path=path, field_name="draw_count", allow_zero=False
                    )

    # Validate attribute_profiles
    profiles = data.get("attribute_profiles")
    if profiles is not None:
        if not isinstance(profiles, dict):
            result.add(file, "attribute_profiles", "expected a mapping")
        else:
            for rarity, archetypes in profiles.items():
                profile_path = f"attribute_profiles.{rarity}"
                if rarity not in VALID_GUEST_RARITIES:
                    result.add(file, profile_path, f"unknown rarity '{rarity}'")
                if not isinstance(archetypes, dict):
                    result.add(file, profile_path, "expected a mapping of archetypes")
                    continue
                for archetype, stats in archetypes.items():
                    arch_path = f"{profile_path}.{archetype}"
                    if archetype not in VALID_GUEST_ARCHETYPES:
                        result.add(file, arch_path, f"unknown archetype '{archetype}'")
                    if not isinstance(stats, dict):
                        result.add(file, arch_path, "expected a mapping of stat values")

    return result


# ---------------------------------------------------------------------------
# Schema: troop_templates.yaml
# ---------------------------------------------------------------------------


def validate_troop_templates(data: dict, *, file: str = "troop_templates.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    troops = data.get("troops")
    if troops is None:
        result.add(file, "<root>", "missing required key 'troops'")
        return result

    if not isinstance(troops, list):
        result.add(file, "troops", "expected a list")
        return result

    _check_unique_keys(troops, "key", result=result, file=file, context="troops")

    for idx, troop in enumerate(troops):
        path = f"troops[{idx}]"
        if not isinstance(troop, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(troop, ["key", "name"], result=result, file=file, path=path)

        for int_field in ("base_attack", "base_defense", "base_hp", "speed_bonus", "priority", "default_count"):
            val = troop.get(int_field)
            if val is not None:
                _check_type(val, (int, float), result=result, file=file, path=path, field_name=int_field)

        recruit = troop.get("recruit")
        if recruit is not None:
            if not isinstance(recruit, dict):
                result.add(file, path, "field 'recruit' expected a mapping")
            else:
                equipment = recruit.get("equipment")
                if equipment is not None and not isinstance(equipment, list):
                    result.add(file, f"{path}.recruit", "field 'equipment' expected a list")

                for recruit_int in ("tech_level", "retainer_cost", "base_duration"):
                    val = recruit.get(recruit_int)
                    if val is not None:
                        _check_type(val, int, result=result, file=file, path=f"{path}.recruit", field_name=recruit_int)

    return result


# ---------------------------------------------------------------------------
# Schema: mission_templates.yaml
# ---------------------------------------------------------------------------


def validate_mission_templates(
    data: dict,
    *,
    file: str = "mission_templates.yaml",
    item_keys: set[str] | None = None,
    troop_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    missions = data.get("missions")
    if missions is None:
        result.add(file, "<root>", "missing required key 'missions'")
        return result

    if not isinstance(missions, list):
        result.add(file, "missions", "expected a list")
        return result

    _check_unique_keys(missions, "key", result=result, file=file, context="missions")

    for idx, mission in enumerate(missions):
        path = f"missions[{idx}]"
        if not isinstance(mission, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(mission, ["key", "name"], result=result, file=file, path=path)

        daily_limit = mission.get("daily_limit")
        if daily_limit is not None:
            _check_type(daily_limit, int, result=result, file=file, path=path, field_name="daily_limit")
            _check_positive(
                daily_limit, result=result, file=file, path=path, field_name="daily_limit", allow_zero=False
            )

        base_travel_time = mission.get("base_travel_time")
        if base_travel_time is not None:
            _check_type(
                base_travel_time, (int, float), result=result, file=file, path=path, field_name="base_travel_time"
            )
            _check_positive(base_travel_time, result=result, file=file, path=path, field_name="base_travel_time")

        # Validate enemy_guests
        enemy_guests = mission.get("enemy_guests")
        if enemy_guests is not None:
            if not isinstance(enemy_guests, list):
                result.add(file, path, "field 'enemy_guests' expected a list")
            else:
                for gi, guest in enumerate(enemy_guests):
                    guest_path = f"{path}.enemy_guests[{gi}]"
                    if isinstance(guest, str):
                        pass  # simple string reference
                    elif isinstance(guest, dict):
                        if "key" not in guest:
                            result.add(file, guest_path, "missing required field 'key'")
                    else:
                        result.add(file, guest_path, f"expected string or mapping, got {type(guest).__name__}")

        # Validate enemy_troops with referential integrity
        enemy_troops = mission.get("enemy_troops")
        if enemy_troops is not None:
            if not isinstance(enemy_troops, dict):
                result.add(file, path, "field 'enemy_troops' expected a mapping")
            elif troop_keys is not None:
                for troop_key, count in enemy_troops.items():
                    if troop_key not in troop_keys:
                        result.add(
                            file,
                            f"{path}.enemy_troops",
                            f"troop key '{troop_key}' not found in troop_templates.yaml",
                        )
                    if isinstance(count, bool) or not isinstance(count, (int, float)) or count < 0:
                        result.add(
                            file,
                            f"{path}.enemy_troops.{troop_key}",
                            f"expected a non-negative number, got {count!r}",
                        )

        # Validate enemy_technology
        enemy_tech = mission.get("enemy_technology")
        if enemy_tech is not None:
            if not isinstance(enemy_tech, dict):
                result.add(file, path, "field 'enemy_technology' expected a mapping")
            else:
                level = enemy_tech.get("level")
                if level is not None:
                    _check_type(
                        level, int, result=result, file=file, path=f"{path}.enemy_technology", field_name="level"
                    )

                guest_level = enemy_tech.get("guest_level")
                if guest_level is not None:
                    _check_type(
                        guest_level,
                        int,
                        result=result,
                        file=file,
                        path=f"{path}.enemy_technology",
                        field_name="guest_level",
                    )

                guest_bonus = enemy_tech.get("guest_bonus")
                if guest_bonus is not None:
                    _check_type(
                        guest_bonus,
                        (int, float),
                        result=result,
                        file=file,
                        path=f"{path}.enemy_technology",
                        field_name="guest_bonus",
                    )

        # Validate drop_table referential integrity
        drop_table = mission.get("drop_table")
        if drop_table is not None:
            if not isinstance(drop_table, dict):
                result.add(file, path, "field 'drop_table' expected a mapping")
            elif item_keys is not None:
                # 'silver' is a special case (resource), not always in item_templates.
                # Entries whose value is a dict with 'choices' are virtual random-pick
                # entries -- the key is a label, not an item key.
                for drop_key, drop_val in drop_table.items():
                    if drop_key == "silver":
                        continue
                    is_random_choice = isinstance(drop_val, dict) and "choices" in drop_val
                    if is_random_choice:
                        # Validate the individual choices instead
                        for choice in drop_val["choices"]:
                            if isinstance(choice, str) and choice not in item_keys:
                                result.add(
                                    file,
                                    f"{path}.drop_table.{drop_key}.choices",
                                    f"choice item key '{choice}' not found in item_templates.yaml",
                                )
                        continue
                    if drop_key not in item_keys:
                        result.add(
                            file,
                            f"{path}.drop_table",
                            f"item key '{drop_key}' not found in item_templates.yaml",
                        )

    return result


# ---------------------------------------------------------------------------
# Schema: forge_equipment.yaml
# ---------------------------------------------------------------------------

VALID_FORGE_CATEGORIES = {"helmet", "armor", "shoes", "sword", "dao", "spear", "bow", "whip"}


def validate_forge_equipment(
    data: dict,
    *,
    file: str = "forge_equipment.yaml",
    item_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    equipment = data.get("equipment")
    if equipment is None:
        result.add(file, "<root>", "missing required key 'equipment'")
        return result

    if not isinstance(equipment, dict):
        result.add(file, "equipment", "expected a mapping")
        return result

    for equip_key, config in equipment.items():
        path = f"equipment.{equip_key}"
        if not isinstance(config, dict):
            result.add(file, path, "expected a mapping")
            continue

        # Check referential integrity with item_templates
        if item_keys is not None and equip_key not in item_keys:
            result.add(file, path, f"equipment key '{equip_key}' not found in item_templates.yaml")

        category = config.get("category")
        if category is not None:
            _check_in(category, VALID_FORGE_CATEGORIES, result=result, file=file, path=path, field_name="category")

        materials = config.get("materials")
        if materials is not None:
            if not isinstance(materials, dict):
                result.add(file, path, "field 'materials' expected a mapping")

        base_duration = config.get("base_duration")
        if base_duration is not None:
            _check_type(base_duration, int, result=result, file=file, path=path, field_name="base_duration")
            _check_positive(
                base_duration, result=result, file=file, path=path, field_name="base_duration", allow_zero=False
            )

        required_forging = config.get("required_forging")
        if required_forging is not None:
            _check_type(required_forging, int, result=result, file=file, path=path, field_name="required_forging")
            _check_positive(
                required_forging, result=result, file=file, path=path, field_name="required_forging", allow_zero=False
            )

    return result


# ---------------------------------------------------------------------------
# Schema: shop_items.yaml
# ---------------------------------------------------------------------------


def validate_shop_items(
    data: dict,
    *,
    file: str = "shop_items.yaml",
    item_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    items = data.get("items")
    if items is None:
        result.add(file, "<root>", "missing required key 'items'")
        return result

    if not isinstance(items, list):
        result.add(file, "items", "expected a list")
        return result

    _check_unique_keys(items, "item_key", result=result, file=file, context="items")

    for idx, entry in enumerate(items):
        path = f"items[{idx}]"
        if not isinstance(entry, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(entry, ["item_key"], result=result, file=file, path=path)

        item_key = entry.get("item_key")
        if item_key is not None and item_keys is not None:
            if item_key not in item_keys:
                result.add(file, path, f"item_key '{item_key}' not found in item_templates.yaml")

        stock = entry.get("stock")
        if stock is not None:
            _check_type(stock, int, result=result, file=file, path=path, field_name="stock")

        daily_refresh = entry.get("daily_refresh")
        if daily_refresh is not None:
            _check_type(daily_refresh, bool, result=result, file=file, path=path, field_name="daily_refresh")

    return result


# ---------------------------------------------------------------------------
# Schema: arena_rules.yaml
# ---------------------------------------------------------------------------


def validate_arena_rules(data: dict, *, file: str = "arena_rules.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    for section in ("registration", "runtime", "rewards"):
        section_data = data.get(section)
        if section_data is None:
            result.add(file, "<root>", f"missing required section '{section}'")
        elif not isinstance(section_data, dict):
            result.add(file, section, "expected a mapping")

    reg = data.get("registration")
    if isinstance(reg, dict):
        for int_field in (
            "max_guests_per_entry",
            "registration_silver_cost",
            "daily_participation_limit",
            "tournament_player_limit",
        ):
            val = reg.get(int_field)
            if val is not None:
                _check_type(val, int, result=result, file=file, path="registration", field_name=int_field)
                _check_positive(
                    val, result=result, file=file, path="registration", field_name=int_field, allow_zero=False
                )

    rewards = data.get("rewards")
    if isinstance(rewards, dict):
        base_coins = rewards.get("base_participation_coins")
        if base_coins is not None:
            _check_type(
                base_coins, int, result=result, file=file, path="rewards", field_name="base_participation_coins"
            )
            _check_positive(base_coins, result=result, file=file, path="rewards", field_name="base_participation_coins")

        rank_bonus = rewards.get("rank_bonus_coins")
        if rank_bonus is not None:
            if not isinstance(rank_bonus, dict):
                result.add(file, "rewards.rank_bonus_coins", "expected a mapping")

    return result


# ---------------------------------------------------------------------------
# Schema: trade_market_rules.yaml
# ---------------------------------------------------------------------------


def validate_trade_market_rules(data: dict, *, file: str = "trade_market_rules.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    listing_fees = data.get("listing_fees")
    if listing_fees is None:
        result.add(file, "<root>", "missing required key 'listing_fees'")
        return result

    if not isinstance(listing_fees, dict):
        result.add(file, "listing_fees", "expected a mapping")
        return result

    for duration, fee in listing_fees.items():
        path = f"listing_fees.{duration}"
        if not isinstance(fee, (int, float)):
            result.add(file, path, f"expected a number, got {type(fee).__name__}")
        elif fee < 0:
            result.add(file, path, f"fee must be >= 0, got {fee}")

    return result


# ---------------------------------------------------------------------------
# Schema: warehouse_production.yaml
# ---------------------------------------------------------------------------

VALID_WAREHOUSE_TECH_KEYS = {"equipment", "experience", "resource"}


def validate_warehouse_production(data: dict, *, file: str = "warehouse_production.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    for tech_key, tech_data in data.items():
        path = tech_key
        if tech_key not in VALID_WAREHOUSE_TECH_KEYS:
            result.add(file, path, f"unknown tech section '{tech_key}'")

        if not isinstance(tech_data, dict):
            result.add(file, path, "expected a mapping")
            continue

        levels = tech_data.get("levels")
        if levels is None:
            result.add(file, path, "missing required key 'levels'")
            continue

        if not isinstance(levels, dict):
            result.add(file, f"{path}.levels", "expected a mapping")
            continue

        for level_key, items in levels.items():
            level_path = f"{path}.levels.{level_key}"
            if not isinstance(items, list):
                result.add(file, level_path, "expected a list of items")
                continue

            for idx, item in enumerate(items):
                item_path = f"{level_path}[{idx}]"
                if not isinstance(item, dict):
                    result.add(file, item_path, "expected a mapping")
                    continue
                _check_required_fields(
                    item,
                    ["item_key", "quantity", "contribution_cost"],
                    result=result,
                    file=file,
                    path=item_path,
                )
                quantity = item.get("quantity")
                if quantity is not None:
                    _check_type(quantity, int, result=result, file=file, path=item_path, field_name="quantity")
                    _check_positive(
                        quantity, result=result, file=file, path=item_path, field_name="quantity", allow_zero=False
                    )
                contribution_cost = item.get("contribution_cost")
                if contribution_cost is not None:
                    _check_type(
                        contribution_cost, int, result=result, file=file, path=item_path, field_name="contribution_cost"
                    )
                    _check_positive(
                        contribution_cost,
                        result=result,
                        file=file,
                        path=item_path,
                        field_name="contribution_cost",
                        allow_zero=False,
                    )

    return result


# ---------------------------------------------------------------------------
# Schema: auction_items.yaml
# ---------------------------------------------------------------------------


def validate_auction_items(
    data: dict,
    *,
    file: str = "auction_items.yaml",
    item_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    settings_data = data.get("settings")
    if settings_data is not None:
        if not isinstance(settings_data, dict):
            result.add(file, "settings", "expected a mapping")
        else:
            cycle_days = settings_data.get("cycle_days")
            if cycle_days is not None:
                _check_type(cycle_days, int, result=result, file=file, path="settings", field_name="cycle_days")
                _check_positive(
                    cycle_days, result=result, file=file, path="settings", field_name="cycle_days", allow_zero=False
                )

    items = data.get("items")
    if items is None:
        result.add(file, "<root>", "missing required key 'items'")
        return result

    if not isinstance(items, list):
        result.add(file, "items", "expected a list")
        return result

    _check_unique_keys(items, "item_key", result=result, file=file, context="items")

    for idx, entry in enumerate(items):
        path = f"items[{idx}]"
        if not isinstance(entry, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(
            entry, ["item_key", "slots", "quantity_per_slot", "starting_price"], result=result, file=file, path=path
        )

        item_key = entry.get("item_key")
        if item_key is not None and item_keys is not None:
            if item_key not in item_keys:
                result.add(file, path, f"item_key '{item_key}' not found in item_templates.yaml")

        for pos_int_field in ("slots", "quantity_per_slot", "starting_price", "min_increment"):
            val = entry.get(pos_int_field)
            if val is not None:
                _check_type(val, int, result=result, file=file, path=path, field_name=pos_int_field)
                _check_positive(val, result=result, file=file, path=path, field_name=pos_int_field, allow_zero=False)

        enabled = entry.get("enabled")
        if enabled is not None:
            _check_type(enabled, bool, result=result, file=file, path=path, field_name="enabled")

    return result


# ---------------------------------------------------------------------------
# Schema: forge_blueprints.yaml
# ---------------------------------------------------------------------------


def validate_forge_blueprints(
    data: dict,
    *,
    file: str = "forge_blueprints.yaml",
    item_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    recipes = data.get("recipes")
    if recipes is None:
        result.add(file, "<root>", "missing required key 'recipes'")
        return result

    if not isinstance(recipes, list):
        result.add(file, "recipes", "expected a list")
        return result

    _check_unique_keys(recipes, "blueprint_key", result=result, file=file, context="recipes")

    for idx, recipe in enumerate(recipes):
        path = f"recipes[{idx}]"
        if not isinstance(recipe, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(
            recipe,
            ["blueprint_key", "result_item_key", "required_forging", "quantity_out"],
            result=result,
            file=file,
            path=path,
        )

        result_item_key = recipe.get("result_item_key")
        if result_item_key is not None and item_keys is not None:
            if result_item_key not in item_keys:
                result.add(file, path, f"result_item_key '{result_item_key}' not found in item_templates.yaml")

        required_forging = recipe.get("required_forging")
        if required_forging is not None:
            _check_type(required_forging, int, result=result, file=file, path=path, field_name="required_forging")
            _check_positive(
                required_forging, result=result, file=file, path=path, field_name="required_forging", allow_zero=False
            )

        quantity_out = recipe.get("quantity_out")
        if quantity_out is not None:
            _check_type(quantity_out, int, result=result, file=file, path=path, field_name="quantity_out")
            _check_positive(
                quantity_out, result=result, file=file, path=path, field_name="quantity_out", allow_zero=False
            )

        costs = recipe.get("costs")
        if costs is not None and not isinstance(costs, dict):
            result.add(file, path, "field 'costs' expected a mapping")

    return result


# ---------------------------------------------------------------------------
# Schema: forge_decompose.yaml
# ---------------------------------------------------------------------------

VALID_DECOMPOSE_RARITIES = {"green", "blue", "purple", "orange"}


def validate_forge_decompose(data: dict, *, file: str = "forge_decompose.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    supported_rarities = data.get("supported_rarities")
    if supported_rarities is None:
        result.add(file, "<root>", "missing required key 'supported_rarities'")
    elif not isinstance(supported_rarities, list):
        result.add(file, "supported_rarities", "expected a list")
    else:
        for rarity in supported_rarities:
            if rarity not in VALID_DECOMPOSE_RARITIES:
                result.add(file, "supported_rarities", f"unknown rarity '{rarity}'")

    # Validate base_materials per rarity
    base_materials = data.get("base_materials")
    if base_materials is not None:
        if not isinstance(base_materials, dict):
            result.add(file, "base_materials", "expected a mapping")
        else:
            for rarity, materials in base_materials.items():
                rarity_path = f"base_materials.{rarity}"
                if rarity not in VALID_DECOMPOSE_RARITIES:
                    result.add(file, rarity_path, f"unknown rarity '{rarity}'")
                if not isinstance(materials, dict):
                    result.add(file, rarity_path, "expected a mapping of material ranges")
                    continue
                for mat_key, mat_range in materials.items():
                    mat_path = f"{rarity_path}.{mat_key}"
                    if not isinstance(mat_range, list) or len(mat_range) != 2:
                        result.add(file, mat_path, "expected a list of [min, max]")
                        continue
                    for i, bound in enumerate(mat_range):
                        if not isinstance(bound, (int, float)) or bound < 0:
                            result.add(file, mat_path, f"bound[{i}] must be a non-negative number, got {bound!r}")

    # Validate chance_rewards per rarity
    chance_rewards = data.get("chance_rewards")
    if chance_rewards is not None:
        if not isinstance(chance_rewards, dict):
            result.add(file, "chance_rewards", "expected a mapping")
        else:
            for rarity, rewards in chance_rewards.items():
                rarity_path = f"chance_rewards.{rarity}"
                if rarity not in VALID_DECOMPOSE_RARITIES:
                    result.add(file, rarity_path, f"unknown rarity '{rarity}'")
                if not isinstance(rewards, dict):
                    result.add(file, rarity_path, "expected a mapping of chance values")
                    continue
                for reward_key, prob in rewards.items():
                    reward_path = f"{rarity_path}.{reward_key}"
                    if not isinstance(prob, (int, float)):
                        result.add(file, reward_path, f"expected a number, got {type(prob).__name__}")
                    elif not (0.0 <= prob <= 1.0):
                        result.add(file, reward_path, f"probability must be between 0 and 1, got {prob}")

    return result


# ---------------------------------------------------------------------------
# Schema: guest_skills.yaml
# ---------------------------------------------------------------------------

VALID_SKILL_RARITIES = {"black", "gray", "green", "red", "blue", "purple", "orange"}
VALID_SKILL_KINDS = {"active", "passive"}


def validate_guest_skills(data: dict, *, file: str = "guest_skills.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    skills = data.get("skills")
    if skills is None:
        result.add(file, "<root>", "missing required key 'skills'")
        return result

    if not isinstance(skills, list):
        result.add(file, "skills", "expected a list")
        return result

    _check_unique_keys(skills, "key", result=result, file=file, context="skills")

    for idx, skill in enumerate(skills):
        path = f"skills[{idx}]"
        if not isinstance(skill, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(skill, ["key", "name", "rarity"], result=result, file=file, path=path)

        rarity = skill.get("rarity")
        if rarity is not None:
            _check_in(rarity, VALID_SKILL_RARITIES, result=result, file=file, path=path, field_name="rarity")

        kind = skill.get("kind")
        if kind is not None:
            _check_in(kind, VALID_SKILL_KINDS, result=result, file=file, path=path, field_name="kind")

        base_power = skill.get("base_power")
        if base_power is not None:
            _check_type(base_power, (int, float), result=result, file=file, path=path, field_name="base_power")
            _check_positive(base_power, result=result, file=file, path=path, field_name="base_power")

        base_probability = skill.get("base_probability")
        if base_probability is not None:
            _check_type(
                base_probability, (int, float), result=result, file=file, path=path, field_name="base_probability"
            )
            if isinstance(base_probability, (int, float)) and not (0.0 <= base_probability <= 1.0):
                result.add(file, path, f"field 'base_probability' must be between 0 and 1, got {base_probability}")

        targets = skill.get("targets")
        if targets is not None:
            _check_type(targets, int, result=result, file=file, path=path, field_name="targets")
            _check_positive(targets, result=result, file=file, path=path, field_name="targets", allow_zero=False)

        required_level = skill.get("required_level")
        if required_level is not None:
            _check_type(required_level, int, result=result, file=file, path=path, field_name="required_level")
            _check_positive(
                required_level, result=result, file=file, path=path, field_name="required_level", allow_zero=False
            )

    return result


# ---------------------------------------------------------------------------
# Schema: recruitment_rarity_weights.yaml
# ---------------------------------------------------------------------------

VALID_RARITY_WEIGHT_KEYS = {"orange", "hermit", "purple", "red", "blue", "green", "gray", "black"}


def validate_recruitment_rarity_weights(
    data: dict, *, file: str = "recruitment_rarity_weights.yaml"
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    total_weight = data.get("total_weight")
    if total_weight is None:
        result.add(file, "<root>", "missing required key 'total_weight'")
    else:
        _check_type(total_weight, int, result=result, file=file, path="<root>", field_name="total_weight")
        _check_positive(
            total_weight, result=result, file=file, path="<root>", field_name="total_weight", allow_zero=False
        )

    weights = data.get("weights")
    if weights is None:
        result.add(file, "<root>", "missing required key 'weights'")
        return result

    if not isinstance(weights, dict):
        result.add(file, "weights", "expected a mapping")
        return result

    for rarity, weight in weights.items():
        path = f"weights.{rarity}"
        if rarity not in VALID_RARITY_WEIGHT_KEYS:
            result.add(file, path, f"unknown rarity '{rarity}'")
        if not isinstance(weight, int):
            result.add(file, path, f"expected int, got {type(weight).__name__}")
        elif weight < 0:
            result.add(file, path, f"weight must be >= 0, got {weight}")

    return result


# ---------------------------------------------------------------------------
# Schema: arena_rewards.yaml
# ---------------------------------------------------------------------------


def validate_arena_rewards(
    data: dict,
    *,
    file: str = "arena_rewards.yaml",
    item_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    rewards = data.get("rewards")
    if rewards is None:
        result.add(file, "<root>", "missing required key 'rewards'")
        return result

    if not isinstance(rewards, list):
        result.add(file, "rewards", "expected a list")
        return result

    _check_unique_keys(rewards, "key", result=result, file=file, context="rewards")

    for idx, entry in enumerate(rewards):
        path = f"rewards[{idx}]"
        if not isinstance(entry, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(entry, ["key", "name", "cost_coins"], result=result, file=file, path=path)

        cost_coins = entry.get("cost_coins")
        if cost_coins is not None:
            _check_type(cost_coins, int, result=result, file=file, path=path, field_name="cost_coins")
            _check_positive(cost_coins, result=result, file=file, path=path, field_name="cost_coins", allow_zero=False)

        daily_limit = entry.get("daily_limit")
        if daily_limit is not None:
            _check_type(daily_limit, int, result=result, file=file, path=path, field_name="daily_limit")
            _check_positive(
                daily_limit, result=result, file=file, path=path, field_name="daily_limit", allow_zero=False
            )

        reward_data = entry.get("rewards")
        if reward_data is not None and not isinstance(reward_data, dict):
            result.add(file, path, "field 'rewards' expected a mapping")

        # Validate random_items referential integrity
        if isinstance(reward_data, dict) and item_keys is not None:
            random_items = reward_data.get("random_items")
            if random_items is not None:
                if not isinstance(random_items, list):
                    result.add(file, f"{path}.rewards", "field 'random_items' expected a list")
                else:
                    for ri, rand_item in enumerate(random_items):
                        ri_path = f"{path}.rewards.random_items[{ri}]"
                        if not isinstance(rand_item, dict):
                            result.add(file, ri_path, "expected a mapping")
                            continue
                        rand_item_key = rand_item.get("item_key")
                        if rand_item_key is not None and rand_item_key not in item_keys:
                            result.add(file, ri_path, f"item_key '{rand_item_key}' not found in item_templates.yaml")
                        weight = rand_item.get("weight")
                        if weight is not None:
                            _check_type(weight, int, result=result, file=file, path=ri_path, field_name="weight")
                            _check_positive(
                                weight, result=result, file=file, path=ri_path, field_name="weight", allow_zero=False
                            )

    return result


# ---------------------------------------------------------------------------
# Schema: smithy_production.yaml
# ---------------------------------------------------------------------------

VALID_SMITHY_CATEGORIES = {"metal", "medicine"}


def validate_smithy_production(data: dict, *, file: str = "smithy_production.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    production = data.get("production")
    if production is None:
        result.add(file, "<root>", "missing required key 'production'")
        return result

    if not isinstance(production, dict):
        result.add(file, "production", "expected a mapping")
        return result

    for item_key, item_data in production.items():
        path = f"production.{item_key}"
        if not isinstance(item_data, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(
            item_data, ["cost_type", "cost_amount", "base_duration"], result=result, file=file, path=path
        )

        cost_amount = item_data.get("cost_amount")
        if cost_amount is not None:
            _check_type(cost_amount, (int, float), result=result, file=file, path=path, field_name="cost_amount")
            _check_positive(
                cost_amount, result=result, file=file, path=path, field_name="cost_amount", allow_zero=False
            )

        base_duration = item_data.get("base_duration")
        if base_duration is not None:
            _check_type(base_duration, int, result=result, file=file, path=path, field_name="base_duration")
            _check_positive(
                base_duration, result=result, file=file, path=path, field_name="base_duration", allow_zero=False
            )

        category = item_data.get("category")
        if category is not None:
            _check_in(category, VALID_SMITHY_CATEGORIES, result=result, file=file, path=path, field_name="category")

    return result


# ---------------------------------------------------------------------------
# Schema: ranch_production.yaml
# ---------------------------------------------------------------------------


def validate_ranch_production(data: dict, *, file: str = "ranch_production.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    production = data.get("production")
    if production is None:
        result.add(file, "<root>", "missing required key 'production'")
        return result

    if not isinstance(production, dict):
        result.add(file, "production", "expected a mapping")
        return result

    for item_key, item_data in production.items():
        path = f"production.{item_key}"
        if not isinstance(item_data, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(item_data, ["grain_cost", "base_duration"], result=result, file=file, path=path)

        grain_cost = item_data.get("grain_cost")
        if grain_cost is not None:
            _check_type(grain_cost, (int, float), result=result, file=file, path=path, field_name="grain_cost")
            _check_positive(grain_cost, result=result, file=file, path=path, field_name="grain_cost", allow_zero=False)

        base_duration = item_data.get("base_duration")
        if base_duration is not None:
            _check_type(base_duration, int, result=result, file=file, path=path, field_name="base_duration")
            _check_positive(
                base_duration, result=result, file=file, path=path, field_name="base_duration", allow_zero=False
            )

    return result


# ---------------------------------------------------------------------------
# Schema: stable_production.yaml
# ---------------------------------------------------------------------------


def validate_stable_production(
    data: dict,
    *,
    file: str = "stable_production.yaml",
    item_keys: set[str] | None = None,
) -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    production = data.get("production")
    if production is None:
        result.add(file, "<root>", "missing required key 'production'")
        return result

    if not isinstance(production, dict):
        result.add(file, "production", "expected a mapping")
        return result

    for equip_key, item_data in production.items():
        path = f"production.{equip_key}"
        if not isinstance(item_data, dict):
            result.add(file, path, "expected a mapping")
            continue

        if item_keys is not None and equip_key not in item_keys:
            result.add(file, path, f"production key '{equip_key}' not found in item_templates.yaml")

        _check_required_fields(item_data, ["grain_cost", "base_duration"], result=result, file=file, path=path)

        grain_cost = item_data.get("grain_cost")
        if grain_cost is not None:
            _check_type(grain_cost, (int, float), result=result, file=file, path=path, field_name="grain_cost")
            _check_positive(grain_cost, result=result, file=file, path=path, field_name="grain_cost", allow_zero=False)

        base_duration = item_data.get("base_duration")
        if base_duration is not None:
            _check_type(base_duration, int, result=result, file=file, path=path, field_name="base_duration")
            _check_positive(
                base_duration, result=result, file=file, path=path, field_name="base_duration", allow_zero=False
            )

    return result


# ---------------------------------------------------------------------------
# Schema: guild_rules.yaml
# ---------------------------------------------------------------------------


def validate_guild_rules(data: dict, *, file: str = "guild_rules.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    for section in ("pagination", "creation", "contribution"):
        section_data = data.get(section)
        if section_data is None:
            result.add(file, "<root>", f"missing required section '{section}'")
        elif not isinstance(section_data, dict):
            result.add(file, section, "expected a mapping")

    pagination = data.get("pagination")
    if isinstance(pagination, dict):
        for int_field in ("guild_list_page_size", "guild_hall_display_limit"):
            val = pagination.get(int_field)
            if val is not None:
                _check_type(val, int, result=result, file=file, path="pagination", field_name=int_field)
                _check_positive(
                    val, result=result, file=file, path="pagination", field_name=int_field, allow_zero=False
                )

    contribution = data.get("contribution")
    if isinstance(contribution, dict):
        min_donation = contribution.get("min_donation_amount")
        if min_donation is not None:
            _check_type(
                min_donation,
                (int, float),
                result=result,
                file=file,
                path="contribution",
                field_name="min_donation_amount",
            )
            _check_positive(
                min_donation,
                result=result,
                file=file,
                path="contribution",
                field_name="min_donation_amount",
                allow_zero=False,
            )

        daily_limits = contribution.get("daily_limits")
        if daily_limits is not None:
            if not isinstance(daily_limits, dict):
                result.add(file, "contribution.daily_limits", "expected a mapping")
            else:
                for resource, limit in daily_limits.items():
                    if not isinstance(limit, (int, float)) or limit < 0:
                        result.add(
                            file,
                            f"contribution.daily_limits.{resource}",
                            f"expected a non-negative number, got {limit!r}",
                        )

    hero_pool = data.get("hero_pool")
    if hero_pool is not None:
        if not isinstance(hero_pool, dict):
            result.add(file, "hero_pool", "expected a mapping")
        else:
            for int_field in ("slot_limit", "battle_lineup_limit", "replace_cooldown_seconds"):
                val = hero_pool.get(int_field)
                if val is not None:
                    _check_type(val, int, result=result, file=file, path="hero_pool", field_name=int_field)
                    _check_positive(
                        val, result=result, file=file, path="hero_pool", field_name=int_field, allow_zero=False
                    )

    return result


# ---------------------------------------------------------------------------
# Schema: guest_growth_rules.yaml
# ---------------------------------------------------------------------------

VALID_GROWTH_RARITIES = {"black", "gray", "green", "red", "blue", "purple", "orange"}
VALID_GROWTH_ARCHETYPES = {"military", "civil"}


def validate_guest_growth_rules(data: dict, *, file: str = "guest_growth_rules.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    # Validate rarity_hp_profiles
    hp_profiles = data.get("rarity_hp_profiles")
    if hp_profiles is not None:
        if not isinstance(hp_profiles, dict):
            result.add(file, "rarity_hp_profiles", "expected a mapping")
        else:
            for rarity, profile in hp_profiles.items():
                path = f"rarity_hp_profiles.{rarity}"
                if rarity not in VALID_GROWTH_RARITIES:
                    result.add(file, path, f"unknown rarity '{rarity}'")
                if not isinstance(profile, dict):
                    result.add(file, path, "expected a mapping")
                    continue
                base = profile.get("base")
                if base is not None:
                    _check_type(base, (int, float), result=result, file=file, path=path, field_name="base")
                    _check_positive(base, result=result, file=file, path=path, field_name="base", allow_zero=False)

    # Validate rarity_skill_point_gains
    skill_point_gains = data.get("rarity_skill_point_gains")
    if skill_point_gains is not None:
        if not isinstance(skill_point_gains, dict):
            result.add(file, "rarity_skill_point_gains", "expected a mapping")
        else:
            for rarity, gain in skill_point_gains.items():
                path = f"rarity_skill_point_gains.{rarity}"
                if rarity not in VALID_GROWTH_RARITIES:
                    result.add(file, path, f"unknown rarity '{rarity}'")
                if not isinstance(gain, (int, float)) or gain < 0:
                    result.add(file, path, f"expected a non-negative number, got {gain!r}")

    # Validate rarity_attribute_growth_range
    growth_ranges = data.get("rarity_attribute_growth_range")
    if growth_ranges is not None:
        if not isinstance(growth_ranges, dict):
            result.add(file, "rarity_attribute_growth_range", "expected a mapping")
        else:
            for rarity, growth_range in growth_ranges.items():
                path = f"rarity_attribute_growth_range.{rarity}"
                if rarity not in VALID_GROWTH_RARITIES:
                    result.add(file, path, f"unknown rarity '{rarity}'")
                if not isinstance(growth_range, list) or len(growth_range) != 2:
                    result.add(file, path, "expected a list of [min, max]")

    # Validate archetype_attribute_weights
    archetype_weights = data.get("archetype_attribute_weights")
    if archetype_weights is not None:
        if not isinstance(archetype_weights, dict):
            result.add(file, "archetype_attribute_weights", "expected a mapping")
        else:
            for archetype, weights in archetype_weights.items():
                path = f"archetype_attribute_weights.{archetype}"
                if archetype not in VALID_GROWTH_ARCHETYPES:
                    result.add(file, path, f"unknown archetype '{archetype}'")
                if not isinstance(weights, dict):
                    result.add(file, path, "expected a mapping of attribute weights")

    return result


# ---------------------------------------------------------------------------
# Schema: technology_templates.yaml
# ---------------------------------------------------------------------------

VALID_TECH_CATEGORIES = {"basic", "martial", "production"}


def validate_technology_templates(data: dict, *, file: str = "technology_templates.yaml") -> ValidationResult:
    result = ValidationResult()

    if not isinstance(data, dict):
        result.add(file, "<root>", "expected a mapping at root level")
        return result

    # Validate categories section
    categories = data.get("categories")
    if categories is not None:
        if not isinstance(categories, list):
            result.add(file, "categories", "expected a list")
        else:
            _check_unique_keys(categories, "key", result=result, file=file, context="categories")
            for idx, cat in enumerate(categories):
                cat_path = f"categories[{idx}]"
                if not isinstance(cat, dict):
                    result.add(file, cat_path, "expected a mapping")
                    continue
                _check_required_fields(cat, ["key", "name"], result=result, file=file, path=cat_path)

    # Validate technologies list
    technologies = data.get("technologies")
    if technologies is None:
        result.add(file, "<root>", "missing required key 'technologies'")
        return result

    if not isinstance(technologies, list):
        result.add(file, "technologies", "expected a list")
        return result

    _check_unique_keys(technologies, "key", result=result, file=file, context="technologies")

    for idx, tech in enumerate(technologies):
        path = f"technologies[{idx}]"
        if not isinstance(tech, dict):
            result.add(file, path, "expected a mapping")
            continue

        _check_required_fields(
            tech,
            ["key", "name", "category", "effect_type", "max_level", "base_cost"],
            result=result,
            file=file,
            path=path,
        )

        category = tech.get("category")
        if category is not None:
            _check_in(category, VALID_TECH_CATEGORIES, result=result, file=file, path=path, field_name="category")

        max_level = tech.get("max_level")
        if max_level is not None:
            _check_type(max_level, int, result=result, file=file, path=path, field_name="max_level")
            _check_positive(max_level, result=result, file=file, path=path, field_name="max_level", allow_zero=False)

        base_cost = tech.get("base_cost")
        if base_cost is not None:
            _check_type(base_cost, (int, float), result=result, file=file, path=path, field_name="base_cost")
            _check_positive(base_cost, result=result, file=file, path=path, field_name="base_cost", allow_zero=False)

        effect_per_level = tech.get("effect_per_level")
        if effect_per_level is not None:
            _check_type(
                effect_per_level, (int, float), result=result, file=file, path=path, field_name="effect_per_level"
            )

    return result


# ---------------------------------------------------------------------------
# High-level: validate all config files at once
# ---------------------------------------------------------------------------


def validate_all_configs(data_dir: str | Path) -> ValidationResult:
    """Load and validate all YAML config files from the data directory."""
    data_path = Path(data_dir)
    result = ValidationResult()

    def _load(filename: str) -> dict | None:
        filepath = data_path / filename
        if not filepath.exists():
            result.add(filename, "<file>", f"file not found: {filepath}")
            return None
        data = load_yaml_data(filepath, logger=logger, context=f"validate {filename}", default=None)
        if data is None:
            result.add(filename, "<file>", "failed to load YAML or file is empty")
            return None
        return data

    # Load all configs
    item_data = _load("item_templates.yaml")
    building_data = _load("building_templates.yaml")
    guest_data = _load("guest_templates.yaml")
    troop_data = _load("troop_templates.yaml")
    mission_data = _load("mission_templates.yaml")
    forge_data = _load("forge_equipment.yaml")
    shop_data = _load("shop_items.yaml")
    arena_data = _load("arena_rules.yaml")
    trade_data = _load("trade_market_rules.yaml")
    warehouse_data = _load("warehouse_production.yaml")
    auction_data = _load("auction_items.yaml")
    blueprints_data = _load("forge_blueprints.yaml")
    decompose_data = _load("forge_decompose.yaml")
    skills_data = _load("guest_skills.yaml")
    rarity_weights_data = _load("recruitment_rarity_weights.yaml")
    arena_rewards_data = _load("arena_rewards.yaml")
    smithy_data = _load("smithy_production.yaml")
    ranch_data = _load("ranch_production.yaml")
    stable_data = _load("stable_production.yaml")
    guild_data = _load("guild_rules.yaml")
    growth_data = _load("guest_growth_rules.yaml")
    tech_data = _load("technology_templates.yaml")

    # Build cross-reference key sets for referential integrity checks
    item_keys: set[str] | None = None
    if item_data is not None:
        result.merge(validate_item_templates(item_data))
        items_list = item_data.get("items") or []
        if isinstance(items_list, list):
            item_keys = {str(item["key"]) for item in items_list if isinstance(item, dict) and item.get("key")}

    troop_keys: set[str] | None = None
    if troop_data is not None:
        result.merge(validate_troop_templates(troop_data))
        troops_list = troop_data.get("troops") or []
        if isinstance(troops_list, list):
            troop_keys = {str(troop["key"]) for troop in troops_list if isinstance(troop, dict) and troop.get("key")}

    if building_data is not None:
        result.merge(validate_building_templates(building_data))

    if guest_data is not None:
        result.merge(validate_guest_templates(guest_data))

    if mission_data is not None:
        result.merge(validate_mission_templates(mission_data, item_keys=item_keys, troop_keys=troop_keys))

    if forge_data is not None:
        result.merge(validate_forge_equipment(forge_data, item_keys=item_keys))

    if shop_data is not None:
        result.merge(validate_shop_items(shop_data, item_keys=item_keys))

    if arena_data is not None:
        result.merge(validate_arena_rules(arena_data))

    if trade_data is not None:
        result.merge(validate_trade_market_rules(trade_data))

    if warehouse_data is not None:
        result.merge(validate_warehouse_production(warehouse_data))

    if auction_data is not None:
        result.merge(validate_auction_items(auction_data, item_keys=item_keys))

    if blueprints_data is not None:
        result.merge(validate_forge_blueprints(blueprints_data, item_keys=item_keys))

    if decompose_data is not None:
        result.merge(validate_forge_decompose(decompose_data))

    if skills_data is not None:
        result.merge(validate_guest_skills(skills_data))

    if rarity_weights_data is not None:
        result.merge(validate_recruitment_rarity_weights(rarity_weights_data))

    if arena_rewards_data is not None:
        result.merge(validate_arena_rewards(arena_rewards_data, item_keys=item_keys))

    if smithy_data is not None:
        result.merge(validate_smithy_production(smithy_data))

    if ranch_data is not None:
        result.merge(validate_ranch_production(ranch_data))

    if stable_data is not None:
        result.merge(validate_stable_production(stable_data, item_keys=item_keys))

    if guild_data is not None:
        result.merge(validate_guild_rules(guild_data))

    if growth_data is not None:
        result.merge(validate_guest_growth_rules(growth_data))

    if tech_data is not None:
        result.merge(validate_technology_templates(tech_data))

    return result


def get_supported_yaml_configs() -> tuple[str, ...]:
    """Return the YAML config filenames currently covered by schema validation."""
    return SUPPORTED_YAML_CONFIGS
