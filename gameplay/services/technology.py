"""
技术系统服务模块

提供技术配置加载、玩家技术管理和加成计算功能。
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F

from core.utils.time_scale import scale_duration
from .cache import invalidate_home_stats_cache
from .notifications import notify_user
from core.exceptions import (
    InsufficientResourceError,
    TechnologyNotFoundError,
    TechnologyConcurrentUpgradeLimitError,
    TechnologyUpgradeInProgressError,
    TechnologyMaxLevelError,
)

from ..constants import MAX_CONCURRENT_TECH_UPGRADES

logger = logging.getLogger(__name__)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_templates_data(raw: Any, *, path: str) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    logger.error("technology templates root must be a mapping: path=%s type=%s", path, type(raw).__name__)
    return {}


@lru_cache(maxsize=1)
def load_technology_templates() -> Dict[str, Any]:
    """
    加载技术配置文件。

    Returns:
        包含 categories, technologies, troop_classes 的字典
    """

    path = os.path.join(settings.BASE_DIR, "data", "technology_templates.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return _normalize_templates_data(raw, path=path)
    except FileNotFoundError:
        logger.error("technology_templates.yaml not found: %s", path)
        return {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        logger.exception("Failed to load technology templates from %s: %s", path, exc)
        return {}


@lru_cache(maxsize=1)
def _build_technology_index() -> Dict[str, Dict[str, Any]]:
    """
    构建技术索引字典，将 O(n) 查找优化为 O(1)。

    Returns:
        {tech_key: tech_config} 索引字典
    """
    data = load_technology_templates()
    result: Dict[str, Dict[str, Any]] = {}
    for tech in data.get("technologies", []) or []:
        if not isinstance(tech, dict):
            continue
        tech_key = str(tech.get("key") or "").strip()
        if not tech_key:
            continue
        result[tech_key] = tech
    return result


@lru_cache(maxsize=1)
def _build_troop_to_class_index() -> Dict[str, str]:
    """
    构建兵种到分类的索引字典，将 O(n*m) 查找优化为 O(1)。

    Returns:
        {troop_key: class_key} 索引字典
    """
    data = load_technology_templates()
    index = {}
    for class_key, class_info in (data.get("troop_classes", {}) or {}).items():
        if not isinstance(class_info, dict):
            continue
        for troop_key in class_info.get("troops", []) or []:
            troop_key_str = str(troop_key).strip()
            if troop_key_str:
                index[troop_key_str] = str(class_key)
    return index


def clear_technology_cache() -> None:
    """
    清理技术配置缓存。

    在运行时修改配置文件后调用此函数使缓存失效。
    也可用于测试环境重置。
    """
    load_technology_templates.cache_clear()
    _build_technology_index.cache_clear()
    _build_troop_to_class_index.cache_clear()


def get_technology_template(tech_key: str) -> Optional[Dict[str, Any]]:
    """
    获取单个技术的配置模板。

    时间复杂度: O(1)（使用索引缓存）

    Args:
        tech_key: 技术标识

    Returns:
        技术配置字典，不存在则返回 None
    """
    return _build_technology_index().get(tech_key)


def get_technologies_by_category(category: str) -> List[Dict[str, Any]]:
    """
    获取指定分类的所有技术。

    Args:
        category: 分类标识 (basic, martial, production)

    Returns:
        技术配置列表
    """
    data = load_technology_templates()
    return [tech for tech in (data.get("technologies", []) or []) if isinstance(tech, dict) and tech.get("category") == category]


def get_categories() -> List[Dict[str, Any]]:
    """获取所有技术分类。"""
    data = load_technology_templates()
    categories = data.get("categories", [])
    if isinstance(categories, list):
        return categories
    return []


def get_troop_classes() -> Dict[str, Any]:
    """获取兵种分类映射。"""
    data = load_technology_templates()
    troop_classes = data.get("troop_classes", {})
    if isinstance(troop_classes, dict):
        return troop_classes
    return {}


def calculate_upgrade_cost(tech_key: str, current_level: int) -> int:
    """
    计算技术升级到下一级所需的银两。

    公式: base_cost * (growth^current_level)
    使用指数增长，平衡科技研究成本：
    - 0->1级: 8000 * 1.5^0 = 8,000
    - 1->2级: 8000 * 1.5^1 = 12,000
    - 2->3级: 8000 * 1.5^2 = 18,000
    - 5->6级: 8000 * 1.5^5 = 60,750
    - 9->10级: 8000 * 1.5^9 = 307,546
    - 19->20级: 8000 * 1.5^19 = 17,734,702

    Args:
        tech_key: 技术标识
        current_level: 当前等级

    Returns:
        升级所需银两，如果技术不存在返回 0
    """
    template = get_technology_template(tech_key)
    if not template:
        return 0
    base_cost = _coerce_int(template.get("base_cost", 8000), 8000)
    growth = 1.5  # 指数增长系数
    return int(base_cost * (growth ** current_level))


def get_troop_class_for_key(troop_key: str) -> Optional[str]:
    """
    根据兵种 key 获取其所属分类。

    时间复杂度: O(1)（使用索引缓存）

    Args:
        troop_key: 兵种标识 (如 dao_ke, jian_shi)

    Returns:
        分类标识 (如 dao, jian)，不存在则返回 None
    """
    return _build_troop_to_class_index().get(troop_key)


def get_player_technology_level(manor, tech_key: str) -> int:
    """
    获取玩家某项技术的等级。

    Args:
        manor: 庄园实例
        tech_key: 技术标识

    Returns:
        技术等级，未研究返回 0
    """
    from ..models import PlayerTechnology
    try:
        tech = manor.technologies.get(tech_key=tech_key)
        return tech.level
    except PlayerTechnology.DoesNotExist:
        return 0


def get_player_technologies(manor) -> Dict[str, int]:
    """
    获取玩家所有技术等级。

    Args:
        manor: 庄园实例

    Returns:
        {tech_key: level} 字典
    """
    return {tech.tech_key: tech.level for tech in manor.technologies.all()}


def get_technology_display_data(manor, category: str) -> List[Dict[str, Any]]:
    """
    获取用于页面显示的技术数据。

    Args:
        manor: 庄园实例
        category: 分类标识

    Returns:
        包含技术信息和玩家等级的列表
    """

    technologies = get_technologies_by_category(category)

    # 获取玩家技术记录（包含升级状态）
    player_techs = {
        pt.tech_key: pt
        for pt in manor.technologies.all()
    }

    result = []
    for tech in technologies:
        tech_key = tech["key"]
        player_tech = player_techs.get(tech_key)
        level = player_tech.level if player_tech else 0
        max_level = tech.get("max_level", 10)

        # 计算升级成本（使用统一的成本计算函数）
        if level < max_level:
            upgrade_cost = calculate_upgrade_cost(tech_key, level)
        else:
            upgrade_cost = None

        # 计算升级时间（支持从配置读取 base_time）
        if level < max_level:
            base_time = tech.get("base_time", 60)  # 默认60秒，特殊技能可配置更长
            upgrade_duration = scale_duration(base_time * (1.4 ** level), minimum=1)
        else:
            upgrade_duration = None

        # 升级状态
        is_upgrading = player_tech.is_upgrading if player_tech else False
        upgrade_complete_at = player_tech.upgrade_complete_at if player_tech else None
        time_remaining = player_tech.time_remaining if player_tech else 0

        # 计算当前效果（转为百分比数字，如 0.10 -> 10）
        effect_per_level = tech.get("effect_per_level", 0.10)
        current_effect = level * effect_per_level * 100
        next_effect = (level + 1) * effect_per_level * 100 if level < max_level else None

        result.append({
            "key": tech_key,
            "name": tech["name"],
            "description": tech.get("description", ""),
            "category": tech.get("category"),
            "troop_class": tech.get("troop_class"),
            "effect_type": tech.get("effect_type"),
            "level": level,
            "max_level": max_level,
            "upgrade_cost": upgrade_cost,
            "upgrade_duration": upgrade_duration,
            "current_effect": current_effect,
            "next_effect": next_effect,
            "effect_per_level": effect_per_level,
            "can_upgrade": level < max_level and not is_upgrading,
            "is_upgrading": is_upgrading,
            "upgrade_complete_at": upgrade_complete_at,
            "time_remaining": time_remaining,
        })

    return result


def get_martial_technologies_grouped(manor) -> List[Dict[str, Any]]:
    """
    获取按兵种分组的武艺技术数据。

    Args:
        manor: 庄园实例

    Returns:
        [{"class_key": "dao", "class_name": "刀类", "technologies": [...]}]
    """
    technologies = get_technology_display_data(manor, "martial")
    troop_classes = get_troop_classes()

    # 按兵种分组
    grouped = {}
    for tech in technologies:
        troop_class = str(tech.get("troop_class") or "")
        if troop_class not in grouped:
            class_info = troop_classes.get(troop_class, {})
            grouped[troop_class] = {
                "class_key": troop_class,
                "class_name": class_info.get("name", troop_class),
                "technologies": [],
            }
        grouped[troop_class]["technologies"].append(tech)

    # 按固定顺序排列
    order = ["dao", "qiang", "jian", "quan", "gong"]
    result = []
    for class_key in order:
        if class_key in grouped:
            result.append(grouped[class_key])

    return result


def schedule_technology_completion(tech, eta_seconds: int) -> None:
    """
    调度后台任务，在技术升级计时器结束时完成升级。

    Args:
        tech: PlayerTechnology 实例
        eta_seconds: 预计完成时间（秒）
    """

    countdown = max(0, int(eta_seconds))
    try:
        from gameplay.tasks import complete_technology_upgrade
    except Exception:
        logger.warning("Unable to import complete_technology_upgrade task; skip scheduling", exc_info=True)
        return
    transaction.on_commit(lambda: complete_technology_upgrade.apply_async(args=[tech.id], countdown=countdown))


def upgrade_technology(manor, tech_key: str) -> Dict[str, Any]:
    """
    开始升级玩家技术（耗时升级）。

    Args:
        manor: 庄园实例
        tech_key: 技术标识

    Returns:
        {"success": bool, "message": str, "duration": int}

    Raises:
        ValueError: 升级失败时抛出异常
    """
    from django.utils import timezone
    from datetime import timedelta
    from ..models import PlayerTechnology
    from .resources import spend_resources_locked

    template = get_technology_template(tech_key)
    if not template:
        raise TechnologyNotFoundError(tech_key)

    max_level = template.get("max_level", 10)

    with transaction.atomic():
        # 锁住庄园行，确保并发上限校验在并发请求下仍然可靠
        from ..models import Manor
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)

        # 获取或创建玩家技术记录
        tech, created = PlayerTechnology.objects.get_or_create(
            manor=locked_manor,
            tech_key=tech_key,
            defaults={"level": 0}
        )

        # 检查是否正在升级
        if tech.is_upgrading:
            raise TechnologyUpgradeInProgressError(tech_key, template["name"])

        if tech.level >= max_level:
            raise TechnologyMaxLevelError(tech_key, template["name"], max_level)

        upgrading_count = PlayerTechnology.objects.filter(manor=locked_manor, is_upgrading=True).count()
        if upgrading_count >= MAX_CONCURRENT_TECH_UPGRADES:
            raise TechnologyConcurrentUpgradeLimitError(MAX_CONCURRENT_TECH_UPGRADES)

        # 计算升级成本（使用服务层函数）
        cost = calculate_upgrade_cost(tech_key, tech.level)

        # 检查并扣除银两
        if locked_manor.silver < cost:
            raise InsufficientResourceError("silver", cost, locked_manor.silver)

        spend_resources_locked(locked_manor, {"silver": cost}, reason="tech_upgrade", note=f"升级{template['name']}")

        # 累计银两花费，计算声望
        from .prestige import add_prestige_silver_locked
        add_prestige_silver_locked(locked_manor, cost)

        # 计算升级时间并开始升级
        duration = tech.upgrade_duration()
        tech.is_upgrading = True
        tech.upgrade_complete_at = timezone.now() + timedelta(seconds=duration)
        tech.save(update_fields=["is_upgrading", "upgrade_complete_at"])

        # 调度 Celery 任务
        schedule_technology_completion(tech, duration)

    return {
        "success": True,
        "message": f"{template['name']} 开始升级，预计 {duration} 秒后完成",
        "duration": duration,
    }


def finalize_technology_upgrade(tech, send_notification: bool = False) -> bool:
    """
    完成技术升级。

    Args:
        tech: PlayerTechnology 实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成升级
    """
    from django.utils import timezone
    from ..models import Message

    if not getattr(tech, "pk", None):
        return False
    now = timezone.now()
    updated = (
        tech.__class__.objects.filter(
            pk=tech.pk,
            is_upgrading=True,
            upgrade_complete_at__isnull=False,
            upgrade_complete_at__lte=now,
        ).update(
            level=F("level") + 1,
            is_upgrading=False,
            upgrade_complete_at=None,
            updated_at=now,
        )
    )
    if updated != 1:
        return False

    tech = tech.__class__.objects.select_related("manor").get(pk=tech.pk)

    # 获取技术名称
    template = get_technology_template(tech.tech_key)
    tech_name = template["name"] if template else tech.tech_key

    if send_notification:
        from .messages import create_message

        create_message(
            manor=tech.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{tech_name} 研究完成",
            body=f"当前等级 Lv{tech.level}",
        )

        notify_user(
            tech.manor.user_id,
            {
                "kind": "system",
                "title": f"{tech_name} 研究完成",
                "tech_key": tech.tech_key,
                "level": tech.level,
            },
            log_context="technology upgrade notification",
        )

    invalidate_home_stats_cache(tech.manor_id)
    return True


def refresh_technology_upgrades(manor) -> int:
    """
    刷新庄园所有技术的升级状态。

    Args:
        manor: 庄园实例

    Returns:
        完成升级的技术数量
    """
    from django.utils import timezone

    min_interval = getattr(settings, "MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS", 0)
    if min_interval > 0 and getattr(manor, "pk", None):
        cache_key = f"tech:refresh:{manor.pk}"
        try:
            if not cache.add(cache_key, "1", timeout=min_interval):
                return 0
        except Exception as exc:
            logger.debug("Technology refresh throttle cache unavailable: %s", exc, exc_info=True)

    completed = 0
    upgrading_techs = list(
        manor.technologies.filter(
            is_upgrading=True,
            upgrade_complete_at__lte=timezone.now()
        )
    )

    for tech in upgrading_techs:
        if finalize_technology_upgrade(tech, send_notification=True):
            completed += 1

    return completed


def get_tech_bonus_from_levels(levels: Dict[str, int], effect_type: str, troop_class: Optional[str] = None) -> float:
    """
    纯数据版科技加成计算（供 AI/敌方使用）。

    Args:
        levels: 科技等级字典 {tech_key: level}
        effect_type: 效果类型 (如 troop_attack, march_speed)
        troop_class: 兵种分类 (如 dao, jian)，部分效果类型需要

    Returns:
        加成倍率 (如 0.3 表示 +30%)
    """
    data = load_technology_templates()
    total = 0.0
    for tech in data.get("technologies", []) or []:
        if not isinstance(tech, dict):
            continue
        if tech.get("effect_type") != effect_type:
            continue
        tech_key = str(tech.get("key") or "").strip()
        if not tech_key:
            continue
        tech_troop_class = tech.get("troop_class")
        if tech_troop_class and troop_class and tech_troop_class != troop_class:
            continue
        level = _coerce_int(levels.get(tech_key, 0), 0)
        if level <= 0:
            continue
        effect_per_level = _coerce_float(tech.get("effect_per_level", 0.10), 0.10)
        total += level * effect_per_level
    return total


def get_tech_bonus(manor, effect_type: str, troop_class: str = None) -> float:
    """
    获取技术提供的加成值。

    Args:
        manor: 庄园实例
        effect_type: 效果类型 (如 troop_attack, march_speed)
        troop_class: 兵种分类 (如 dao, jian)，部分效果类型需要

    Returns:
        加成倍率 (如 0.3 表示 +30%)
    """
    return get_tech_bonus_from_levels(get_player_technologies(manor), effect_type, troop_class)


def build_uniform_tech_levels(level: int) -> Dict[str, int]:
    """
    将单一等级映射到所有科技键，并按 max_level 截断。

    Args:
        level: 统一等级

    Returns:
        {tech_key: level} 字典
    """
    data = load_technology_templates()
    base_level = max(0, _coerce_int(level, 0))
    resolved: Dict[str, int] = {}
    for tech in data.get("technologies", []) or []:
        if not isinstance(tech, dict):
            continue
        tech_key = str(tech.get("key") or "").strip()
        if not tech_key:
            continue
        max_level = max(0, _coerce_int(tech.get("max_level", base_level), base_level))
        resolved[tech_key] = max(0, min(base_level, max_level))
    return resolved


def resolve_enemy_tech_levels(config: Dict[str, Any]) -> Dict[str, int]:
    """
    简单合并规则：
    1) level 统一铺底；2) levels 逐个键覆盖。

    Args:
        config: 敌方科技配置字典

    Returns:
        {tech_key: level} 字典
    """
    if not config or not isinstance(config, dict):
        return {}
    levels = {}
    if config.get("level") is not None:
        levels = build_uniform_tech_levels(_coerce_int(config.get("level", 0), 0))
    for key, val in (config.get("levels") or {}).items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        levels[normalized_key] = max(0, _coerce_int(val, 0))
    return levels


def get_guest_stat_bonuses(config: Dict[str, Any]) -> Dict[str, float]:
    """
    根据配置计算门客的属性加成。

    Args:
        config: 敌方科技配置字典，可包含：
            - guest_bonus: 直接百分比加成，如 0.2 表示 +20%
            - guest_bonus_flat: 固定值加成字典 {"attack": 100, "defense": 50}

    Returns:
        {"attack": 0.2, "defense": 0.2, "hp": 0.2, "agility": 0.1} 加成字典
    """
    if not config:
        return {}

    bonuses = {}

    # 方式1：统一百分比加成
    if "guest_bonus" in config:
        bonus_percent = _coerce_float(config.get("guest_bonus", 0), 0.0)
        bonuses["attack"] = bonus_percent
        bonuses["defense"] = bonus_percent
        bonuses["hp"] = bonus_percent
        bonuses["agility"] = bonus_percent * 0.5  # 敏捷减半

    # 方式2：固定值加成（暂时不实现，保留接口）
    # if "guest_bonus_flat" in config:
    #     bonuses["flat"] = config.get("guest_bonus_flat", {})

    return bonuses


def get_resource_production_bonus_from_levels(
    levels: Dict[str, int],
    resource_type: str,
    building_key: Optional[str] = None,
) -> float:
    """
    纯数据版资源产出加成计算。

    支持在 technology_templates.yaml 的 resource_production 科技中通过以下字段限定生效范围：
    - building_key: str（单个建筑 key）
    - building_keys: [str, ...]（多个建筑 key）

    Args:
        levels: 科技等级字典 {tech_key: level}
        resource_type: 资源类型 (grain, silver)
        building_key: 可选，产出来源建筑 key（如 farm）

    Returns:
        加成倍率
    """
    data = load_technology_templates()

    total_bonus = 0.0
    for tech in data.get("technologies", []) or []:
        if not isinstance(tech, dict):
            continue
        if tech.get("effect_type") != "resource_production":
            continue
        if tech.get("resource_type") != resource_type:
            continue

        # 检查建筑限制
        required_building_key = tech.get("building_key")
        required_building_keys = tech.get("building_keys")
        if required_building_key or required_building_keys:
            if not building_key:
                continue
            if required_building_key and building_key != required_building_key:
                continue
            if required_building_keys and building_key not in required_building_keys:
                continue

        tech_key = str(tech.get("key") or "").strip()
        if not tech_key:
            continue
        level = _coerce_int(levels.get(tech_key, 0), 0)
        if level <= 0:
            continue
        effect_per_level = _coerce_float(tech.get("effect_per_level", 0.05), 0.05)
        total_bonus += level * effect_per_level

    return total_bonus


def get_resource_production_bonus(
    manor, resource_type: str, building_key: Optional[str] = None
) -> float:
    """
    获取资源产出加成。

    Args:
        manor: 庄园实例
        resource_type: 资源类型 (grain, silver)
        building_key: 可选，产出来源建筑 key（如 farm）。
            当科技模板配置了 building_key/building_keys 时，将据此限定生效范围。

    Returns:
        加成倍率
    """
    return get_resource_production_bonus_from_levels(
        get_player_technologies(manor),
        resource_type,
        building_key=building_key,
    )


def get_troop_stat_bonuses(manor, troop_key: str, tech_levels: Optional[Dict[str, int]] = None) -> Dict[str, float]:
    """
    获取兵种的所有属性加成。

    Args:
        manor: 庄园实例
        troop_key: 兵种标识
        tech_levels: 可选的科技等级字典（供敌方使用）

    Returns:
        {"attack": 0.2, "defense": 0.1, ...} 加成字典
    """
    troop_class = get_troop_class_for_key(troop_key)
    if not troop_class:
        return {}

    levels = tech_levels if tech_levels is not None else get_player_technologies(manor)

    bonuses = {}
    stat_types = [
        ("troop_attack", "attack"),
        ("troop_defense", "defense"),
        ("troop_agility", "agility"),
        ("troop_hp", "hp"),
    ]

    for effect_type, stat_key in stat_types:
        bonus = get_tech_bonus_from_levels(levels, effect_type, troop_class)
        if bonus > 0:
            bonuses[stat_key] = bonus

    return bonuses


def get_march_speed_bonus(manor) -> float:
    """获取行军速度加成倍率。"""
    return get_tech_bonus(manor, "march_speed")


def get_building_cost_reduction(manor) -> float:
    """获取建筑成本减免倍率。"""
    return get_tech_bonus(manor, "building_cost_reduction")
