"""
铁匠铺装备锻造服务模块

提供装备锻造相关功能。
"""

from __future__ import annotations

import copy
import logging
import os
import random
from datetime import timedelta
from functools import lru_cache
from typing import Any, Dict, List, cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration
from core.utils.yaml_loader import load_yaml_data

from ...constants import BuildingKeys
from ...models import EquipmentProduction, Manor

logger = logging.getLogger(__name__)

# 装备配置
# 锻造技等级需求：1,3,5,7,9级分别解锁不同等级装备
# 材料：铜、锡、铁
EQUIPMENT_CONFIG: Dict[str, Dict[str, Any]] = {
    # ==================== 头盔 ====================
    "equip_bumao": {
        "category": "helmet",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_niupimao": {
        "category": "helmet",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_tieyekui": {
        "category": "helmet",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    # ==================== 护甲 ====================
    "equip_bupao": {
        "category": "armor",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_shengpijia": {
        "category": "armor",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_housipao": {
        "category": "armor",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_shapijia": {
        "category": "armor",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 鞋子 ====================
    "equip_buxie": {
        "category": "shoes",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_yangpixue": {
        "category": "shoes",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_gangpianxue": {
        "category": "shoes",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_yanyuxue": {
        "category": "shoes",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 剑 ====================
    "equip_duanjian": {
        "category": "sword",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_changjian": {
        "category": "sword",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_qingmangjian": {
        "category": "sword",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_duanmajian": {
        "category": "sword",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 刀 ====================
    "equip_duandao": {
        "category": "dao",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_dakandao": {
        "category": "dao",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_tongchangdao": {
        "category": "dao",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_jingtiedao": {
        "category": "dao",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 枪 ====================
    "equip_changqiang": {
        "category": "spear",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_baoweiqiang": {
        "category": "spear",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_hutoumao": {
        "category": "spear",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_pansheqiang": {
        "category": "spear",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 弓 ====================
    "equip_changgong": {
        "category": "bow",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_fanqugong": {
        "category": "bow",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_tietaigong": {
        "category": "bow",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_shenbigong": {
        "category": "bow",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 鞭 ====================
    "equip_changbian": {
        "category": "whip",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_niupibian": {
        "category": "whip",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_jicibian": {
        "category": "whip",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_jiulonggangbian": {
        "category": "whip",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    "equip_mingshejiebian": {
        "category": "whip",
        "materials": {"tie": 30},
        "base_duration": 360,
        "required_forging": 9,
    },
}

# 装备类别
EQUIPMENT_CATEGORIES = {
    "helmet": "头盔",
    "armor": "衣服",
    "shoes": "鞋子",
    "sword": "剑",
    "dao": "刀",
    "spear": "枪",
    "bow": "弓",
    "whip": "鞭",
}

# 材料名称兜底映射（优先从 ItemTemplate 读取名称）。
# 若模板缺失，则直接回退为 key，避免在代码中维护第二份名称来源。
MATERIAL_NAMES: Dict[str, str] = {}


def _get_item_name_map(keys: set[str]) -> Dict[str, str]:
    if not keys:
        return {}
    from ...models import ItemTemplate

    return {tpl.key: tpl.name for tpl in ItemTemplate.objects.filter(key__in=keys).only("key", "name")}


WEAPON_KEYWORD_TO_CATEGORY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sword", ("jian",)),
    ("dao", ("dao",)),
    ("spear", ("qiang", "mao")),
    ("bow", ("gong",)),
    ("whip", ("bian",)),
)

DECOMPOSE_WEAPON_CATEGORIES: set[str] = {"sword", "dao", "spear", "bow", "whip"}
DECOMPOSE_CATEGORIES: Dict[str, str] = {
    "helmet": "头盔",
    "armor": "衣服",
    "shoes": "鞋子",
    "weapon": "武器",
    "device": "器械",
}


def infer_equipment_category(item_key: str, effect_type: str | None = None) -> str | None:
    """推断装备分类，优先使用锻造配置，缺失时按 effect_type/key 兜底。"""
    config = EQUIPMENT_CONFIG.get(item_key)
    if config:
        category = config.get("category")
        if isinstance(category, str) and category:
            return category

    normalized_effect_type = (effect_type or "").strip()
    if normalized_effect_type == "equip_helmet":
        return "helmet"
    if normalized_effect_type == "equip_armor":
        return "armor"
    if normalized_effect_type == "equip_shoes":
        return "shoes"
    if normalized_effect_type == "equip_weapon":
        key_lower = (item_key or "").lower()
        for category, keywords in WEAPON_KEYWORD_TO_CATEGORY:
            if any(keyword in key_lower for keyword in keywords):
                return category
    if normalized_effect_type == "equip_device":
        return "device"
    return None


def to_decompose_category(equipment_category: str | None) -> str | None:
    """分解分类映射：剑/刀/枪/弓/鞭统一归类为武器。"""
    if not equipment_category:
        return None
    if equipment_category in DECOMPOSE_WEAPON_CATEGORIES:
        return "weapon"
    return equipment_category


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
        normalized = [str(item).strip() for item in supported_rarities if str(item).strip()]
        if normalized:
            config["supported_rarities"] = normalized

    rarity_labels = raw.get("rarity_labels")
    if isinstance(rarity_labels, dict):
        for rarity, label in rarity_labels.items():
            rarity_key = str(rarity).strip()
            label_value = str(label).strip()
            if rarity_key and label_value:
                config["rarity_labels"][rarity_key] = label_value

    rarity_order = raw.get("rarity_order")
    if isinstance(rarity_order, dict):
        for rarity, value in rarity_order.items():
            rarity_key = str(rarity).strip()
            if not rarity_key:
                continue
            config["rarity_order"][rarity_key] = _coerce_int(value, config["rarity_order"].get(rarity_key, 0))

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


@lru_cache(maxsize=1)
def load_forge_decompose_config() -> Dict[str, Any]:
    """加载铁匠铺分解配置。"""
    path = os.path.join(settings.BASE_DIR, "data", "forge_decompose.yaml")
    raw = load_yaml_data(
        path,
        logger=logger,
        context="forge decompose config",
        default=DEFAULT_FORGE_DECOMPOSE_CONFIG,
    )
    return _normalize_decompose_config(raw)


def clear_forge_decompose_cache() -> None:
    """清理铁匠铺分解配置缓存。"""
    load_forge_decompose_config.cache_clear()


DEFAULT_FORGE_BLUEPRINT_CONFIG: Dict[str, Any] = {"recipes": []}


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


@lru_cache(maxsize=1)
def load_forge_blueprint_config() -> Dict[str, Any]:
    """加载铁匠铺图纸合成配置。"""
    path = os.path.join(settings.BASE_DIR, "data", "forge_blueprints.yaml")
    raw = load_yaml_data(
        path,
        logger=logger,
        context="forge blueprint config",
        default=DEFAULT_FORGE_BLUEPRINT_CONFIG,
    )
    return _normalize_blueprint_config(raw)


@lru_cache(maxsize=1)
def _build_blueprint_recipe_index() -> Dict[str, Dict[str, Any]]:
    config = load_forge_blueprint_config()
    result: Dict[str, Dict[str, Any]] = {}
    for recipe in config.get("recipes", []) or []:
        key = str(recipe.get("blueprint_key") or "").strip()
        if key:
            result[key] = recipe
    return result


def clear_forge_blueprint_cache() -> None:
    """清理铁匠铺图纸配置缓存。"""
    load_forge_blueprint_config.cache_clear()
    _build_blueprint_recipe_index.cache_clear()


def get_blueprint_synthesis_options(manor: Manor) -> List[Dict[str, Any]]:
    """获取可显示的图纸合成卡片（仅显示玩家仓库中拥有图纸的配方）。"""
    from ...models import InventoryItem, ItemTemplate
    from ..technology import get_player_technology_level

    config = load_forge_blueprint_config()
    recipes = config.get("recipes", []) or []
    if not recipes:
        return []

    all_keys: set[str] = set()
    for recipe in recipes:
        all_keys.add(recipe["blueprint_key"])
        all_keys.add(recipe["result_item_key"])
        all_keys.update(recipe.get("costs", {}).keys())

    template_map = {tpl.key: tpl for tpl in ItemTemplate.objects.filter(key__in=all_keys)}
    inventory_items = (
        InventoryItem.objects.filter(
            manor=manor,
            template__key__in=all_keys,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .select_related("template")
        .order_by("id")
    )

    quantities: Dict[str, int] = {}
    for item in inventory_items:
        key = item.template.key
        quantities[key] = quantities.get(key, 0) + item.quantity

    forging_level = get_player_technology_level(manor, "forging")
    options: List[Dict[str, Any]] = []
    for recipe in recipes:
        blueprint_key = recipe["blueprint_key"]
        blueprint_count = quantities.get(blueprint_key, 0)
        if blueprint_count <= 0:
            continue

        result_key = recipe["result_item_key"]
        quantity_out = recipe.get("quantity_out", 1)
        required_forging = recipe.get("required_forging", 1)
        costs = recipe.get("costs", {})

        costs_info: List[Dict[str, Any]] = []
        max_by_cost = blueprint_count
        can_afford = True
        for cost_key, cost_amount in costs.items():
            current_amount = quantities.get(cost_key, 0)
            cost_template = template_map.get(cost_key)
            costs_info.append(
                {
                    "key": cost_key,
                    "name": cost_template.name if cost_template else cost_key,
                    "required": cost_amount,
                    "current": current_amount,
                }
            )
            if cost_amount > 0:
                max_by_cost = min(max_by_cost, current_amount // cost_amount)
            if current_amount < cost_amount:
                can_afford = False

        is_unlocked = forging_level >= required_forging
        max_synthesis_quantity = max(0, max_by_cost)
        blueprint_template = template_map.get(blueprint_key)
        result_template = template_map.get(result_key)
        options.append(
            {
                "blueprint_key": blueprint_key,
                "blueprint_name": blueprint_template.name if blueprint_template else blueprint_key,
                "blueprint_count": blueprint_count,
                "result_key": result_key,
                "result_name": result_template.name if result_template else result_key,
                "result_effect_type": str(result_template.effect_type or "") if result_template else "",
                "result_quantity": quantity_out,
                "required_forging": required_forging,
                "description": recipe.get("description", ""),
                "costs": costs_info,
                "max_synthesis_quantity": max_synthesis_quantity,
                "is_unlocked": is_unlocked,
                "can_afford": can_afford,
                "can_synthesize": is_unlocked and can_afford and max_synthesis_quantity > 0,
            }
        )

    options.sort(key=lambda row: (row["required_forging"], row["result_name"]), reverse=True)
    return options


def synthesize_equipment_with_blueprint(manor: Manor, blueprint_key: str, quantity: int = 1) -> Dict[str, Any]:
    """按图纸合成装备。"""
    from ...models import InventoryItem, ItemTemplate
    from ...models import Manor as ManorModel
    from ..inventory import add_item_to_inventory_locked, consume_inventory_item_locked
    from ..technology import get_player_technology_level

    if quantity < 1:
        raise ValueError("合成数量至少为1")

    recipe = _build_blueprint_recipe_index().get(blueprint_key)
    if not recipe:
        raise ValueError("无效的图纸")

    required_forging = int(recipe.get("required_forging", 1))
    forging_level = get_player_technology_level(manor, "forging")
    if forging_level < required_forging:
        raise ValueError(f"需要锻造技{required_forging}级才能合成")

    result_item_key = recipe["result_item_key"]
    result_template = ItemTemplate.objects.filter(key=result_item_key).only("key", "name", "effect_type").first()
    if not result_template:
        raise ValueError("图纸配置错误：产物不存在")
    if not str(result_template.effect_type or "").startswith("equip_"):
        raise ValueError("图纸配置错误：产物必须是装备")

    consume_requirements: Dict[str, int] = {blueprint_key: quantity}
    for cost_key, cost_amount in recipe.get("costs", {}).items():
        total = int(cost_amount) * quantity
        consume_requirements[cost_key] = consume_requirements.get(cost_key, 0) + total

    template_names = {
        tpl.key: tpl.name
        for tpl in ItemTemplate.objects.filter(key__in=consume_requirements.keys()).only("key", "name")
    }

    with transaction.atomic():
        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)
        locked_items = {
            item.template.key: item
            for item in InventoryItem.objects.select_for_update()
            .select_related("template")
            .filter(
                manor=locked_manor,
                template__key__in=consume_requirements.keys(),
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
        }

        for need_key, need_amount in consume_requirements.items():
            item = locked_items.get(need_key)
            if not item or item.quantity < need_amount:
                need_name = template_names.get(need_key, need_key)
                raise ValueError(f"{need_name}不足")

        for need_key, need_amount in consume_requirements.items():
            consume_inventory_item_locked(locked_items[need_key], need_amount)

        output_quantity = int(recipe.get("quantity_out", 1)) * quantity
        add_item_to_inventory_locked(locked_manor, result_item_key, output_quantity)

    return {
        "blueprint_key": blueprint_key,
        "result_key": result_item_key,
        "result_name": result_template.name,
        "quantity": output_quantity,
        "craft_times": quantity,
    }


@lru_cache(maxsize=1)
def get_recruitment_equipment_keys() -> set[str]:
    """获取用于募兵的装备 key 集合（这些装备不可分解）。"""
    try:
        from ..recruitment.recruitment import load_troop_templates
    except Exception:
        return set()

    data = load_troop_templates()
    if not isinstance(data, dict):
        return set()

    equipment_keys: set[str] = set()
    for troop in data.get("troops", []):
        if not isinstance(troop, dict):
            continue
        recruit = troop.get("recruit") or {}
        if not isinstance(recruit, dict):
            continue
        for item_key in recruit.get("equipment", []) or []:
            if isinstance(item_key, str) and item_key:
                equipment_keys.add(item_key)
    return equipment_keys


def get_decomposable_equipment_options(manor: Manor, category: str | None = None) -> List[Dict[str, Any]]:
    """
    获取可分解装备列表。

    规则：
    - 必须是装备（effect_type 以 equip_ 开头）
    - 稀有度为绿色及以上
    - 不在募兵装备列表中
    """
    from ...models import InventoryItem

    config = load_forge_decompose_config()
    supported_rarities = set(config["supported_rarities"])
    rarity_labels: Dict[str, str] = config["rarity_labels"]
    rarity_order: Dict[str, int] = config["rarity_order"]
    recruit_equipment_keys = get_recruitment_equipment_keys()

    query = (
        InventoryItem.objects.filter(
            manor=manor,
            quantity__gt=0,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            template__effect_type__startswith="equip_",
            template__rarity__in=supported_rarities,
        )
        .select_related("template")
        .order_by("template__name")
    )
    if recruit_equipment_keys:
        query = query.exclude(template__key__in=recruit_equipment_keys)

    options: list[dict[str, Any]] = []
    for item in query:
        item_category = infer_equipment_category(item.template.key, item.template.effect_type)
        decompose_category = to_decompose_category(item_category)
        if category and decompose_category != category:
            continue

        rarity = item.template.rarity
        options.append(
            {
                "key": item.template.key,
                "name": item.template.name,
                "rarity": rarity,
                "rarity_label": rarity_labels.get(rarity, rarity),
                "quantity": item.quantity,
                "effect_type": item.template.effect_type,
                "category": decompose_category,
                "category_name": (
                    DECOMPOSE_CATEGORIES.get(decompose_category, decompose_category) if decompose_category else ""
                ),
            }
        )

    options.sort(key=lambda row: (-rarity_order.get(row["rarity"], 0), row["name"]))
    return options


def _roll_decompose_rewards(rarity: str, quantity: int, config: Dict[str, Any]) -> Dict[str, int]:
    supported_rarities = set(config["supported_rarities"])
    if rarity not in supported_rarities:
        raise ValueError("仅绿色及以上装备可分解")

    base_materials_map: Dict[str, Dict[str, list[int]]] = config["base_materials"]
    chance_rewards_map: Dict[str, Dict[str, float]] = config["chance_rewards"]
    base_materials = base_materials_map.get(rarity)
    chance_rewards = chance_rewards_map.get(rarity)
    if not base_materials or chance_rewards is None:
        raise ValueError(f"分解配置缺失：{rarity}")

    rewards: Dict[str, int] = {}

    for _ in range(quantity):
        for mat_key, amount_range in base_materials.items():
            min_amount, max_amount = amount_range
            amount = random.randint(min_amount, max_amount)
            if amount > 0:
                rewards[mat_key] = rewards.get(mat_key, 0) + amount

        for reward_key, probability in chance_rewards.items():
            if random.random() < probability:
                rewards[reward_key] = rewards.get(reward_key, 0) + 1

    return rewards


def decompose_equipment(manor: Manor, equipment_key: str, quantity: int = 1) -> Dict[str, Any]:
    """
    分解装备并发放材料。

    Args:
        manor: 庄园实例
        equipment_key: 装备 key
        quantity: 分解数量

    Returns:
        {
            "equipment_key": str,
            "equipment_name": str,
            "quantity": int,
            "rewards": dict[str, int],
        }
    """
    from ...models import InventoryItem
    from ...models import Manor as ManorModel
    from ..inventory import add_item_to_inventory_locked, consume_inventory_item_locked

    if quantity < 1:
        raise ValueError("分解数量至少为1")

    if equipment_key in get_recruitment_equipment_keys():
        raise ValueError("用于募兵（招募护院）的装备不可分解")

    config = load_forge_decompose_config()
    supported_rarities = set(config["supported_rarities"])

    with transaction.atomic():
        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)
        locked_item = (
            InventoryItem.objects.select_for_update()
            .select_related("template")
            .filter(
                manor=locked_manor,
                template__key=equipment_key,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )

        if not locked_item:
            raise ValueError("仓库中没有该装备")
        if locked_item.quantity < quantity:
            raise ValueError("装备数量不足")

        template = locked_item.template
        if not template.effect_type.startswith("equip_"):
            raise ValueError("该物品不是可分解装备")
        if template.rarity not in supported_rarities:
            raise ValueError("仅绿色及以上装备可分解")

        rewards = _roll_decompose_rewards(template.rarity, quantity, config)
        consume_inventory_item_locked(locked_item, quantity)
        for reward_key, reward_amount in rewards.items():
            add_item_to_inventory_locked(locked_manor, reward_key, reward_amount)

    return {
        "equipment_key": equipment_key,
        "equipment_name": template.name,
        "quantity": quantity,
        "rewards": rewards,
    }


def get_forge_speed_bonus(manor: Manor) -> float:
    """
    获取铁匠铺速度加成。

    10级满级提升50%，每级约5%。

    Args:
        manor: 庄园实例

    Returns:
        速度加成倍率（如0.5表示减少50%时间）
    """
    level = manor.get_building_level(BuildingKeys.FORGE)
    return level * 0.05


def get_max_forging_quantity(manor: Manor) -> int:
    """
    获取单次锻造装备的最大数量。

    锻造技每级增加50件上限，满级9级=450件。

    Args:
        manor: 庄园实例

    Returns:
        最大锻造数量
    """
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    # 每级50件，最少1件（0级时也能锻造1件）
    return max(1, forging_level * 50)


def calculate_forging_duration(base_duration: int, manor: Manor) -> int:
    """
    计算实际锻造时间。

    Args:
        base_duration: 基础时间（秒）
        manor: 庄园实例

    Returns:
        实际锻造时间（秒）
    """
    bonus = get_forge_speed_bonus(manor)
    # 加成越高，时间越短
    duration = max(1, int(base_duration * (1 - bonus)))
    return scale_duration(duration, minimum=1)


def has_active_forging(manor: Manor) -> bool:
    """
    检查是否有正在进行的装备锻造。

    Args:
        manor: 庄园实例

    Returns:
        是否有锻造中的装备
    """
    return manor.equipment_productions.filter(status=EquipmentProduction.Status.FORGING).exists()


def get_equipment_options(manor: Manor, category: str = None) -> List[Dict[str, Any]]:
    """
    获取装备锻造选项列表。

    Args:
        manor: 庄园实例
        category: 可选的装备类别过滤

    Returns:
        装备选项列表
    """
    from ..inventory import get_item_quantity
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    max_quantity = get_max_forging_quantity(manor)
    is_forging = has_active_forging(manor)

    filtered_configs: list[tuple[str, Dict[str, Any]]] = []
    for equip_key, config in EQUIPMENT_CONFIG.items():
        if category and config["category"] != category:
            continue
        filtered_configs.append((equip_key, config))

    equipment_keys: set[str] = {equip_key for equip_key, _ in filtered_configs}
    material_keys: set[str] = set()
    for _equip_key, config in filtered_configs:
        material_keys.update(config.get("materials", {}).keys())
    item_name_map = _get_item_name_map(equipment_keys | material_keys)

    options = []
    for equip_key, config in filtered_configs:

        actual_duration = calculate_forging_duration(config["base_duration"], manor)
        required_level = config.get("required_forging", 1)
        is_unlocked = forging_level >= required_level
        equipment_name = item_name_map.get(equip_key, equip_key)

        # 检查材料是否足够
        materials = config.get("materials", {})
        material_info = []
        can_afford = True
        for mat_key, mat_amount in materials.items():
            current_amount = get_item_quantity(manor, mat_key)
            mat_name = item_name_map.get(mat_key, MATERIAL_NAMES.get(mat_key, mat_key))
            material_info.append(
                {
                    "key": mat_key,
                    "name": mat_name,
                    "required": mat_amount,
                    "current": current_amount,
                }
            )
            if current_amount < mat_amount:
                can_afford = False

        options.append(
            {
                "key": equip_key,
                "name": equipment_name,
                "category": config["category"],
                "category_name": EQUIPMENT_CATEGORIES.get(config["category"], config["category"]),
                "materials": material_info,
                "base_duration": config["base_duration"],
                "actual_duration": actual_duration,
                "can_afford": can_afford,
                "required_forging": required_level,
                "is_unlocked": is_unlocked,
                "max_quantity": max_quantity,
                "is_forging": is_forging,
            }
        )
    return options


def get_equipment_by_category(manor: Manor) -> Dict[str, Dict[str, Any]]:
    """
    按类别分组获取装备选项。

    Args:
        manor: 庄园实例

    Returns:
        按类别分组的装备选项
    """
    all_options = get_equipment_options(manor)
    grouped = {}
    for category_key, category_name in EQUIPMENT_CATEGORIES.items():
        grouped[category_key] = {
            "name": category_name,
            "items": [opt for opt in all_options if opt["category"] == category_key],
        }
    return grouped


def start_equipment_forging(manor: Manor, equipment_key: str, quantity: int = 1) -> EquipmentProduction:
    """
    开始锻造装备。

    Args:
        manor: 庄园实例
        equipment_key: 装备key
        quantity: 锻造数量

    Returns:
        EquipmentProduction实例

    Raises:
        ValueError: 参数错误、材料不足、科技等级不足或已有锻造进行中
    """
    if equipment_key not in EQUIPMENT_CONFIG:
        raise ValueError("无效的装备类型")

    config = EQUIPMENT_CONFIG[equipment_key]
    required_level = config.get("required_forging", 1)
    equipment_name_map = _get_item_name_map({equipment_key})
    equipment_name = equipment_name_map.get(equipment_key, equipment_key)

    # 检查锻造技等级
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    if forging_level < required_level:
        raise ValueError(f"需要锻造技{required_level}级才能锻造{equipment_name}")

    # 验证锻造数量
    max_quantity = get_max_forging_quantity(manor)
    if quantity < 1:
        raise ValueError("锻造数量至少为1")
    if quantity > max_quantity:
        raise ValueError(f"锻造技等级限制，单次最多锻造{max_quantity}件")

    # 计算总材料消耗
    materials = config.get("materials", {})
    total_costs = {mat_key: mat_amount * quantity for mat_key, mat_amount in materials.items()}
    material_name_map = _get_item_name_map(set(total_costs.keys()))

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel

        from ...models import InventoryItem
        from ..inventory import consume_inventory_item_locked

        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

        if has_active_forging(locked_manor):
            raise ValueError("已有装备正在锻造中，同时只能锻造一种装备")

        # 扣除材料
        for mat_key, total_amount in total_costs.items():
            item = (
                InventoryItem.objects.select_for_update()
                .select_related("template", "manor")
                .filter(
                    manor=locked_manor,
                    template__key=mat_key,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                )
                .first()
            )
            mat_name = material_name_map.get(mat_key, MATERIAL_NAMES.get(mat_key, mat_key))
            if not item or item.quantity < total_amount:
                raise ValueError(f"{mat_name}不足")
            consume_inventory_item_locked(item, total_amount)

        # 计算实际锻造时间（时间不随数量增加）
        actual_duration = calculate_forging_duration(config["base_duration"], locked_manor)

        # 创建锻造记录
        production = EquipmentProduction.objects.create(
            manor=locked_manor,
            equipment_key=equipment_key,
            equipment_name=equipment_name,
            quantity=quantity,
            material_costs=total_costs,
            base_duration=config["base_duration"],
            actual_duration=actual_duration,
            complete_at=timezone.now() + timedelta(seconds=actual_duration),
        )

        # 调度 Celery 任务
        _schedule_forging_completion(production, actual_duration)

    return production


def _schedule_forging_completion(production: EquipmentProduction, eta_seconds: int) -> None:
    """
    调度锻造完成任务。

    Args:
        production: EquipmentProduction实例
        eta_seconds: 预计完成时间（秒）
    """
    import logging

    from django.db import transaction as db_transaction

    logger = logging.getLogger(__name__)
    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_equipment_forging
    except Exception:
        logger.warning("Unable to import complete_equipment_forging task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(lambda: complete_equipment_forging.apply_async(args=[production.id], countdown=countdown))


def finalize_equipment_forging(production: EquipmentProduction, send_notification: bool = False) -> bool:
    """
    完成装备锻造，将装备添加到玩家仓库。

    Args:
        production: EquipmentProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    from ...models import Message
    from ..utils.notifications import notify_user

    with transaction.atomic():
        # 修复：锁定生产记录，防止并发重复领取
        locked_production = EquipmentProduction.objects.select_for_update().get(pk=production.pk)

        if locked_production.status != EquipmentProduction.Status.FORGING:
            return False
        if locked_production.complete_at > timezone.now():
            return False

        # 添加装备到仓库（按数量添加）
        from ..inventory import add_item_to_inventory_locked

        add_item_to_inventory_locked(
            locked_production.manor, locked_production.equipment_key, locked_production.quantity
        )

        # 更新锻造状态
        locked_production.status = EquipmentProduction.Status.COMPLETED
        locked_production.finished_at = timezone.now()
        locked_production.save(update_fields=["status", "finished_at"])

        # 更新传入对象状态，以便后续通知使用正确信息
        production.status = locked_production.status

    if send_notification:
        from ..utils.messages import create_message

        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        create_message(
            manor=production.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{production.equipment_name}{quantity_text}锻造完成",
            body=f"您的{production.equipment_name}{quantity_text}已锻造完成，请到仓库查收。",
        )

        notify_user(
            production.manor.user_id,
            {
                "kind": "system",
                "title": f"{production.equipment_name}{quantity_text}锻造完成",
                "equipment_key": production.equipment_key,
                "quantity": production.quantity,
            },
            log_context="equipment forging notification",
        )

    return True


def refresh_equipment_forgings(manor: Manor) -> int:
    """
    刷新装备锻造状态，完成所有到期的锻造。

    Args:
        manor: 庄园实例

    Returns:
        完成的锻造数量
    """
    completed = 0
    forging = manor.equipment_productions.filter(
        status=EquipmentProduction.Status.FORGING, complete_at__lte=timezone.now()
    )

    for production in forging:
        if finalize_equipment_forging(production, send_notification=True):
            completed += 1

    return completed


def get_active_forgings(manor: Manor) -> List[EquipmentProduction]:
    """
    获取正在进行的锻造列表。

    Args:
        manor: 庄园实例

    Returns:
        锻造列表
    """
    return list(manor.equipment_productions.filter(status=EquipmentProduction.Status.FORGING).order_by("complete_at"))
