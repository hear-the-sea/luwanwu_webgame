"""
铁匠铺装备锻造服务模块

提供装备锻造相关功能。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Dict, List

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async
from core.utils.time_scale import scale_duration
from core.utils.yaml_loader import load_yaml_data

from ...constants import BuildingKeys
from ...models import EquipmentProduction, Manor
from . import forge_config_helpers as _forge_config_helpers
from . import forge_decompose_helpers as _forge_decompose_helpers
from . import forge_flow_helpers as _forge_flow_helpers
from . import forge_helpers as _forge_helpers

random = _forge_decompose_helpers.random

logger = logging.getLogger(__name__)

# 装备配置
# 锻造技等级需求：1,3,5,7,9级分别解锁不同等级装备
# 材料：铜、锡、铁
DEFAULT_FORGE_EQUIPMENT_CONFIG = _forge_config_helpers.DEFAULT_FORGE_EQUIPMENT_CONFIG
_normalize_equipment_config = _forge_config_helpers._normalize_equipment_config


@lru_cache(maxsize=1)
def load_forge_equipment_config() -> Dict[str, Dict[str, Any]]:
    """加载铁匠铺装备锻造配置。"""
    path = os.path.join(settings.BASE_DIR, "data", "forge_equipment.yaml")
    raw = load_yaml_data(
        path,
        logger=logger,
        context="forge equipment config",
        default={"equipment": DEFAULT_FORGE_EQUIPMENT_CONFIG},
    )
    return _normalize_equipment_config(raw)


def clear_forge_equipment_cache() -> None:
    """清理铁匠铺装备配置缓存。"""
    global EQUIPMENT_CONFIG
    load_forge_equipment_config.cache_clear()
    EQUIPMENT_CONFIG = load_forge_equipment_config()


EQUIPMENT_CONFIG: Dict[str, Dict[str, Any]] = load_forge_equipment_config()


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


WEAPON_KEYWORD_TO_CATEGORY = _forge_helpers.WEAPON_KEYWORD_TO_CATEGORY
DECOMPOSE_WEAPON_CATEGORIES = _forge_helpers.DECOMPOSE_WEAPON_CATEGORIES
DECOMPOSE_CATEGORIES = _forge_helpers.DECOMPOSE_CATEGORIES
_build_equipment_options = _forge_flow_helpers.build_equipment_options
_build_filtered_equipment_configs = _forge_flow_helpers.build_filtered_equipment_configs
_build_total_material_costs = _forge_flow_helpers.build_total_material_costs
_consume_forging_materials_locked = _forge_flow_helpers.consume_forging_materials_locked
_create_equipment_production_record = _forge_flow_helpers.create_equipment_production_record
_load_material_quantity_map = _forge_flow_helpers.load_material_quantity_map
_send_equipment_forging_completion_notification = _forge_flow_helpers.send_equipment_forging_completion_notification
_validate_forging_quantity = _forge_flow_helpers.validate_forging_quantity


def infer_equipment_category(item_key: str, effect_type: str | None = None) -> str | None:
    return _forge_helpers.infer_equipment_category(item_key, effect_type, equipment_config=EQUIPMENT_CONFIG)


def to_decompose_category(equipment_category: str | None) -> str | None:
    return _forge_helpers.to_decompose_category(equipment_category)


DEFAULT_FORGE_DECOMPOSE_CONFIG = _forge_config_helpers.DEFAULT_FORGE_DECOMPOSE_CONFIG
DEFAULT_FORGE_BLUEPRINT_CONFIG = _forge_config_helpers.DEFAULT_FORGE_BLUEPRINT_CONFIG
_coerce_int = _forge_config_helpers._coerce_int
_coerce_float = _forge_config_helpers._coerce_float
_normalize_quantity_range = _forge_config_helpers._normalize_quantity_range
_normalize_decompose_config = _forge_config_helpers._normalize_decompose_config
_normalize_blueprint_recipe = _forge_config_helpers._normalize_blueprint_recipe
_normalize_blueprint_config = _forge_config_helpers._normalize_blueprint_config


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

    all_keys = _forge_helpers.collect_recipe_related_keys(recipes)

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

    quantities = _forge_helpers.build_inventory_quantity_map(inventory_items)

    forging_level = get_player_technology_level(manor, "forging")
    options: List[Dict[str, Any]] = []
    for recipe in recipes:
        option = _forge_helpers.build_blueprint_synthesis_option(
            recipe,
            quantities=quantities,
            template_map=template_map,
            forging_level=forging_level,
        )
        if option is not None:
            options.append(option)

    options.sort(key=lambda row: (row["required_forging"], row["result_name"]), reverse=True)
    return options


def synthesize_equipment_with_blueprint(manor: Manor, blueprint_key: str, quantity: int = 1) -> Dict[str, Any]:
    """按图纸合成装备。"""
    from ...models import InventoryItem, ItemTemplate
    from ...models import Manor as ManorModel
    from ..inventory.core import add_item_to_inventory_locked, consume_inventory_item_locked
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
        option = _forge_decompose_helpers.build_decomposable_equipment_option(
            item,
            rarity_labels=rarity_labels,
            category_labels=DECOMPOSE_CATEGORIES,
            infer_equipment_category=infer_equipment_category,
            to_decompose_category=to_decompose_category,
            category_filter=category,
        )
        if option is not None:
            options.append(option)

    options.sort(key=lambda row: (-rarity_order.get(row["rarity"], 0), row["name"]))
    return options


def _roll_decompose_rewards(rarity: str, quantity: int, config: Dict[str, Any]) -> Dict[str, int]:
    return _forge_decompose_helpers.roll_decompose_rewards(rarity, quantity, config)


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
    from ..inventory.core import add_item_to_inventory_locked, consume_inventory_item_locked

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
    from ...models import InventoryItem
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    max_quantity = get_max_forging_quantity(manor)
    is_forging = has_active_forging(manor)
    filtered_configs = _build_filtered_equipment_configs(equipment_config=EQUIPMENT_CONFIG, category=category)

    equipment_keys: set[str] = {equip_key for equip_key, _ in filtered_configs}
    material_keys = _forge_helpers.collect_material_keys(filtered_configs)
    item_name_map = _get_item_name_map(equipment_keys | material_keys)
    material_quantities = _load_material_quantity_map(
        inventory_item_model=InventoryItem,
        manor=manor,
        material_keys=material_keys,
        build_inventory_quantity_map=_forge_helpers.build_inventory_quantity_map,
    )

    return _build_equipment_options(
        manor=manor,
        filtered_configs=filtered_configs,
        item_name_map=item_name_map,
        material_quantities=material_quantities,
        material_name_fallback_map=MATERIAL_NAMES,
        equipment_categories=EQUIPMENT_CATEGORIES,
        calculate_forging_duration=calculate_forging_duration,
        build_equipment_option=_forge_helpers.build_equipment_option,
        forging_level=forging_level,
        max_quantity=max_quantity,
        is_forging=is_forging,
    )


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
    _validate_forging_quantity(quantity=quantity, max_quantity=max_quantity)

    # 计算总材料消耗
    materials = config.get("materials", {})
    total_costs = _build_total_material_costs(materials=materials, quantity=quantity)
    material_name_map = _get_item_name_map(set(total_costs.keys()))

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel

        from ...models import InventoryItem
        from ..inventory.core import consume_inventory_item_locked

        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

        if has_active_forging(locked_manor):
            raise ValueError("已有装备正在锻造中，同时只能锻造一种装备")

        _consume_forging_materials_locked(
            inventory_item_model=InventoryItem,
            locked_manor=locked_manor,
            total_costs=total_costs,
            material_name_map=material_name_map,
            material_name_fallback_map=MATERIAL_NAMES,
            consume_inventory_item_locked=consume_inventory_item_locked,
        )

        # 计算实际锻造时间（时间不随数量增加）
        actual_duration = calculate_forging_duration(config["base_duration"], locked_manor)

        # 创建锻造记录
        production = _create_equipment_production_record(
            equipment_production_model=EquipmentProduction,
            locked_manor=locked_manor,
            equipment_key=equipment_key,
            equipment_name=equipment_name,
            quantity=quantity,
            total_costs=total_costs,
            base_duration=int(config["base_duration"]),
            actual_duration=actual_duration,
            current_time=timezone.now(),
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
    _forge_flow_helpers.schedule_forging_completion_task(
        production,
        eta_seconds,
        logger=logger,
        transaction_module=transaction,
        safe_apply_async_func=safe_apply_async,
    )


def finalize_equipment_forging(production: EquipmentProduction, send_notification: bool = False) -> bool:
    """
    完成装备锻造，将装备添加到玩家仓库。

    Args:
        production: EquipmentProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    from ..inventory.core import add_item_to_inventory_locked
    from ..utils.notifications import notify_user

    with transaction.atomic():
        locked_production = _forge_flow_helpers.finalize_equipment_production_locked(
            equipment_production_model=EquipmentProduction,
            production=production,
            current_time=timezone.now(),
            add_item_to_inventory_locked=add_item_to_inventory_locked,
        )
        if locked_production is None:
            return False

    production = locked_production
    if send_notification:
        _send_equipment_forging_completion_notification(
            production=production,
            logger=logger,
            notify_user_func=notify_user,
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
