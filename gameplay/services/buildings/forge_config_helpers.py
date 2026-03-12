from __future__ import annotations

import copy
from typing import Any, Dict, List, cast

DEFAULT_FORGE_DECOMPOSE_CONFIG: Dict[str, Any] = {
    "supported_rarities": ["green", "blue", "purple", "orange"],
    "rarity_labels": {
        "green": "绿色",
        "blue": "蓝色",
        "purple": "紫色",
        "orange": "橙色",
    },
    "rarity_order": {
        "orange": 4,
        "purple": 3,
        "blue": 2,
        "green": 1,
    },
    "base_materials": {
        "green": {"tong": [2, 5], "xi": [1, 3], "tie": [1, 2]},
        "blue": {"tong": [4, 8], "xi": [2, 5], "tie": [1, 3]},
        "purple": {"tong": [6, 12], "xi": [4, 8], "tie": [2, 5]},
        "orange": {"tong": [8, 16], "xi": [5, 10], "tie": [3, 7]},
    },
    "chance_rewards": {
        "green": {"wood_essence": 0.75, "copper_essence": 0.25},
        "blue": {
            "wood_essence": 0.75,
            "copper_essence": 0.75,
            "xuan_tie_essence": 0.20,
            "air_stone": 0.12,
            "fire_stone": 0.12,
            "earth_stone": 0.12,
            "water_stone": 0.12,
        },
        "purple": {
            "wood_essence": 0.88,
            "copper_essence": 0.88,
            "xuan_tie_essence": 0.35,
            "air_stone": 0.22,
            "fire_stone": 0.22,
            "earth_stone": 0.22,
            "water_stone": 0.22,
        },
        "orange": {
            "wood_essence": 0.95,
            "copper_essence": 0.95,
            "xuan_tie_essence": 0.50,
            "air_stone": 0.35,
            "fire_stone": 0.35,
            "earth_stone": 0.35,
            "water_stone": 0.35,
        },
    },
}

DEFAULT_FORGE_EQUIPMENT_CONFIG: Dict[str, Dict[str, Any]] = {}

DEFAULT_FORGE_BLUEPRINT_CONFIG: Dict[str, Any] = {"recipes": []}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_quantity_range(raw_value: Any, fallback: list[int]) -> list[int]:
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
        return list(fallback)
    minimum = _coerce_int(raw_value[0], fallback[0])
    maximum = _coerce_int(raw_value[1], fallback[1])
    minimum = max(0, minimum)
    maximum = max(minimum, maximum)
    return [minimum, maximum]


def _normalize_decompose_config(raw: Any) -> Dict[str, Any]:
    config: Dict[str, Any] = copy.deepcopy(DEFAULT_FORGE_DECOMPOSE_CONFIG)
    if not isinstance(raw, dict):
        return config

    supported_rarities = raw.get("supported_rarities")
    if isinstance(supported_rarities, list):
        normalized_supported = [str(rarity).strip() for rarity in supported_rarities if str(rarity).strip()]
        if normalized_supported:
            config["supported_rarities"] = normalized_supported

    rarity_labels = raw.get("rarity_labels")
    if isinstance(rarity_labels, dict):
        for rarity, label in rarity_labels.items():
            rarity_key = str(rarity).strip()
            label_value = str(label).strip()
            if rarity_key and label_value:
                config["rarity_labels"][rarity_key] = label_value

    rarity_order = raw.get("rarity_order")
    if isinstance(rarity_order, dict):
        for rarity, order in rarity_order.items():
            rarity_key = str(rarity).strip()
            if not rarity_key:
                continue
            config["rarity_order"][rarity_key] = max(0, _coerce_int(order, config["rarity_order"].get(rarity_key, 0)))

    base_materials = raw.get("base_materials")
    if isinstance(base_materials, dict):
        for rarity, materials in base_materials.items():
            rarity_key = str(rarity).strip()
            if not rarity_key or not isinstance(materials, dict):
                continue
            fallback_map = cast(Dict[str, list[int]], config["base_materials"].get(rarity_key, {}))
            normalized_map: Dict[str, list[int]] = dict(fallback_map)
            for mat_key, raw_range in materials.items():
                mat_name = str(mat_key).strip()
                if not mat_name:
                    continue
                fallback_range = normalized_map.get(mat_name, [1, 1])
                normalized_map[mat_name] = _normalize_quantity_range(raw_range, fallback_range)
            if normalized_map:
                config["base_materials"][rarity_key] = normalized_map

    chance_rewards = raw.get("chance_rewards")
    if isinstance(chance_rewards, dict):
        for rarity, rewards in chance_rewards.items():
            rarity_key = str(rarity).strip()
            if not rarity_key or not isinstance(rewards, dict):
                continue
            chance_fallback_map = cast(Dict[str, float], config["chance_rewards"].get(rarity_key, {}))
            chance_map: Dict[str, float] = dict(chance_fallback_map)
            for reward_key, raw_prob in rewards.items():
                reward_name = str(reward_key).strip()
                if not reward_name:
                    continue
                fallback_prob = float(chance_map.get(reward_name, 0.0))
                prob = _coerce_float(raw_prob, fallback_prob)
                chance_map[reward_name] = max(0.0, min(1.0, prob))
            if chance_map:
                config["chance_rewards"][rarity_key] = chance_map

    available_rarities = [
        rarity
        for rarity in config["supported_rarities"]
        if rarity in config["base_materials"] and rarity in config["chance_rewards"]
    ]
    if available_rarities:
        config["supported_rarities"] = available_rarities
    else:
        config["supported_rarities"] = list(DEFAULT_FORGE_DECOMPOSE_CONFIG["supported_rarities"])
    return config


def _normalize_equipment_config(raw: Any) -> Dict[str, Dict[str, Any]]:
    root = raw
    if isinstance(raw, dict) and isinstance(raw.get("equipment"), dict):
        root = raw.get("equipment")
    if not isinstance(root, dict):
        return dict(DEFAULT_FORGE_EQUIPMENT_CONFIG)

    config: Dict[str, Dict[str, Any]] = {}
    for raw_key, raw_item in root.items():
        item_key = str(raw_key).strip()
        if not item_key or not isinstance(raw_item, dict):
            continue

        category = str(raw_item.get("category") or "").strip()
        if not category:
            continue

        materials_raw = raw_item.get("materials")
        materials: Dict[str, int] = {}
        if isinstance(materials_raw, dict):
            for mat_key, mat_amount in materials_raw.items():
                normalized_mat_key = str(mat_key).strip()
                if not normalized_mat_key:
                    continue
                amount = max(0, _coerce_int(mat_amount, 0))
                if amount > 0:
                    materials[normalized_mat_key] = amount

        config[item_key] = {
            "category": category,
            "materials": materials,
            "base_duration": max(1, _coerce_int(raw_item.get("base_duration", 1), 1)),
            "required_forging": max(1, _coerce_int(raw_item.get("required_forging", 1), 1)),
        }
    return config


def _normalize_blueprint_recipe(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    blueprint_key = str(raw.get("blueprint_key") or "").strip()
    result_item_key = str(raw.get("result_item_key") or "").strip()
    if not blueprint_key or not result_item_key:
        return None

    required_forging = max(0, _coerce_int(raw.get("required_forging", 1), 1))
    quantity_out = max(1, _coerce_int(raw.get("quantity_out", 1), 1))

    costs_raw = raw.get("costs")
    costs: Dict[str, int] = {}
    if isinstance(costs_raw, dict):
        for key, value in costs_raw.items():
            item_key = str(key).strip()
            if not item_key:
                continue
            amount = _coerce_int(value, 0)
            if amount > 0:
                costs[item_key] = amount

    return {
        "blueprint_key": blueprint_key,
        "result_item_key": result_item_key,
        "required_forging": required_forging,
        "quantity_out": quantity_out,
        "costs": costs,
        "description": str(raw.get("description") or "").strip(),
    }


def _normalize_blueprint_config(raw: Any) -> Dict[str, Any]:
    config: Dict[str, Any] = copy.deepcopy(DEFAULT_FORGE_BLUEPRINT_CONFIG)
    if not isinstance(raw, dict):
        return config

    recipes_raw = raw.get("recipes")
    if not isinstance(recipes_raw, list):
        return config

    recipes: List[Dict[str, Any]] = []
    for entry in recipes_raw:
        normalized = _normalize_blueprint_recipe(entry)
        if normalized:
            recipes.append(normalized)
    config["recipes"] = recipes
    return config
