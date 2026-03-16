"""
技术系统服务模块。

保留历史导入入口，同时把纯规则计算与升级运行态拆到子模块，
降低单文件复杂度并保持现有 monkeypatch/导入兼容性。
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from threading import Lock
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from common.utils.celery import safe_apply_async
from core.exceptions import (
    InsufficientResourceError,
    TechnologyConcurrentUpgradeLimitError,
    TechnologyMaxLevelError,
    TechnologyNotFoundError,
    TechnologyUpgradeInProgressError,
)
from core.utils.time_scale import scale_duration
from core.utils.yaml_loader import ensure_mapping, load_yaml_data

from ..constants import MAX_CONCURRENT_TECH_UPGRADES
from . import technology_helpers as _technology_helpers
from . import technology_rules as _technology_rules
from . import technology_runtime as _technology_runtime
from .utils.cache import invalidate_home_stats_cache
from .utils.notifications import notify_user

logger = logging.getLogger(__name__)
_build_technology_display_entry = _technology_helpers.build_technology_display_entry
_build_technology_upgrade_response = _technology_helpers.build_technology_upgrade_response
_group_martial_technology_entries = _technology_helpers.group_martial_technology_entries
_resolve_technology_name = _technology_helpers.resolve_technology_name
_send_technology_completion_notification = _technology_helpers.send_technology_completion_notification
_coerce_int = _technology_rules.coerce_int
_coerce_float = _technology_rules.coerce_float
TECHNOLOGY_TEMPLATES_PATH = settings.BASE_DIR / "data" / "technology_templates.yaml"

_LOCAL_TECH_REFRESH_FALLBACK: dict[int, float] = {}
_LOCAL_TECH_REFRESH_FALLBACK_LOCK = Lock()
_LOCAL_TECH_REFRESH_FALLBACK_MAX_SIZE = 5000


def _should_skip_tech_refresh_by_local_fallback(manor_id: int, min_interval: int) -> bool:
    return _technology_runtime.should_skip_tech_refresh_by_local_fallback(
        _LOCAL_TECH_REFRESH_FALLBACK,
        state_lock=_LOCAL_TECH_REFRESH_FALLBACK_LOCK,
        max_size=_LOCAL_TECH_REFRESH_FALLBACK_MAX_SIZE,
        manor_id=manor_id,
        min_interval=min_interval,
        monotonic_func=time.monotonic,
    )


@lru_cache(maxsize=1)
def load_technology_templates() -> Dict[str, Any]:
    raw = load_yaml_data(
        TECHNOLOGY_TEMPLATES_PATH,
        logger=logger,
        context="technology templates",
        default={},
    )
    return ensure_mapping(raw, logger=logger, context="technology templates root")


@lru_cache(maxsize=1)
def _build_technology_index() -> Dict[str, Dict[str, Any]]:
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
    load_technology_templates.cache_clear()
    _build_technology_index.cache_clear()
    _build_troop_to_class_index.cache_clear()
    with _LOCAL_TECH_REFRESH_FALLBACK_LOCK:
        _LOCAL_TECH_REFRESH_FALLBACK.clear()


def get_technology_template(tech_key: str) -> Optional[Dict[str, Any]]:
    return _build_technology_index().get(tech_key)


def get_technologies_by_category(category: str) -> List[Dict[str, Any]]:
    data = load_technology_templates()
    return [
        tech
        for tech in (data.get("technologies", []) or [])
        if isinstance(tech, dict) and tech.get("category") == category
    ]


def get_categories() -> List[Dict[str, Any]]:
    data = load_technology_templates()
    categories = data.get("categories", [])
    if isinstance(categories, list):
        return categories
    return []


def get_troop_classes() -> Dict[str, Any]:
    data = load_technology_templates()
    troop_classes = data.get("troop_classes", {})
    if isinstance(troop_classes, dict):
        return troop_classes
    return {}


def calculate_upgrade_cost(tech_key: str, current_level: int) -> int:
    return _technology_rules.calculate_upgrade_cost(
        get_technology_template(tech_key),
        current_level,
        coerce_int_func=_coerce_int,
        coerce_float_func=_coerce_float,
    )


def get_troop_class_for_key(troop_key: str) -> Optional[str]:
    return _build_troop_to_class_index().get(troop_key)


def get_player_technology_level(manor, tech_key: str) -> int:
    from ..models import PlayerTechnology

    try:
        tech = manor.technologies.get(tech_key=tech_key)
        return tech.level
    except PlayerTechnology.DoesNotExist:
        return 0


def get_player_technologies(manor) -> Dict[str, int]:
    return {tech.tech_key: tech.level for tech in manor.technologies.all()}


def get_technology_display_data(manor, category: str) -> List[Dict[str, Any]]:
    technologies = get_technologies_by_category(category)
    player_techs = {pt.tech_key: pt for pt in manor.technologies.all()}
    return [
        _build_technology_display_entry(
            tech=tech,
            player_tech=player_techs.get(tech["key"]),
            calculate_upgrade_cost=calculate_upgrade_cost,
            scale_duration=scale_duration,
        )
        for tech in technologies
    ]


def get_martial_technologies_grouped(manor) -> List[Dict[str, Any]]:
    return _group_martial_technology_entries(
        get_technology_display_data(manor, "martial"),
        get_troop_classes(),
    )


def schedule_technology_completion(tech, eta_seconds: int) -> None:
    _technology_helpers.schedule_technology_completion_task(
        tech,
        eta_seconds,
        logger=logger,
        transaction_module=transaction,
        safe_apply_async_func=safe_apply_async,
    )


def upgrade_technology(manor, tech_key: str) -> Dict[str, Any]:
    return _technology_runtime.upgrade_technology(
        manor,
        tech_key,
        get_technology_template_func=get_technology_template,
        calculate_upgrade_cost_func=calculate_upgrade_cost,
        max_concurrent_tech_upgrades=MAX_CONCURRENT_TECH_UPGRADES,
        schedule_technology_completion_func=schedule_technology_completion,
        build_technology_upgrade_response_func=_build_technology_upgrade_response,
        transaction_module=transaction,
        technology_not_found_error_cls=TechnologyNotFoundError,
        technology_upgrade_in_progress_error_cls=TechnologyUpgradeInProgressError,
        technology_max_level_error_cls=TechnologyMaxLevelError,
        technology_concurrent_upgrade_limit_error_cls=TechnologyConcurrentUpgradeLimitError,
        insufficient_resource_error_cls=InsufficientResourceError,
    )


def finalize_technology_upgrade(tech, send_notification: bool = False) -> bool:
    return _technology_runtime.finalize_technology_upgrade(
        tech,
        get_technology_template_func=get_technology_template,
        resolve_technology_name_func=_resolve_technology_name,
        send_technology_completion_notification_func=_send_technology_completion_notification,
        notify_user_func=notify_user,
        invalidate_home_stats_cache_func=invalidate_home_stats_cache,
        logger=logger,
        send_notification=send_notification,
    )


def refresh_technology_upgrades(manor) -> int:
    return _technology_runtime.refresh_technology_upgrades(
        manor,
        settings_obj=settings,
        cache_backend=cache,
        logger=logger,
        should_skip_tech_refresh_by_local_fallback_func=_should_skip_tech_refresh_by_local_fallback,
        finalize_technology_upgrade_func=finalize_technology_upgrade,
    )


def get_tech_bonus_from_levels(levels: Dict[str, int], effect_type: str, troop_class: Optional[str] = None) -> float:
    data = load_technology_templates()
    return _technology_rules.get_tech_bonus_from_templates(
        data.get("technologies", []) or [],
        levels,
        effect_type,
        troop_class=troop_class,
        coerce_int_func=_coerce_int,
        coerce_float_func=_coerce_float,
    )


def get_tech_bonus(manor, effect_type: str, troop_class: str = None) -> float:
    return get_tech_bonus_from_levels(get_player_technologies(manor), effect_type, troop_class)


def build_uniform_tech_levels(level: int) -> Dict[str, int]:
    data = load_technology_templates()
    return _technology_rules.build_uniform_tech_levels(
        data.get("technologies", []) or [],
        level,
        coerce_int_func=_coerce_int,
    )


def resolve_enemy_tech_levels(config: Dict[str, Any]) -> Dict[str, int]:
    return _technology_rules.resolve_enemy_tech_levels(
        config,
        build_uniform_tech_levels_func=build_uniform_tech_levels,
        coerce_int_func=_coerce_int,
    )


def get_guest_stat_bonuses(config: Dict[str, Any]) -> Dict[str, float]:
    return _technology_rules.get_guest_stat_bonuses(
        config,
        coerce_float_func=_coerce_float,
    )


def get_resource_production_bonus_from_levels(
    levels: Dict[str, int],
    resource_type: str,
    building_key: Optional[str] = None,
) -> float:
    data = load_technology_templates()
    return _technology_rules.get_resource_production_bonus_from_templates(
        data.get("technologies", []) or [],
        levels,
        resource_type,
        building_key=building_key,
        coerce_int_func=_coerce_int,
        coerce_float_func=_coerce_float,
    )


def get_resource_production_bonus(manor, resource_type: str, building_key: Optional[str] = None) -> float:
    return get_resource_production_bonus_from_levels(
        get_player_technologies(manor),
        resource_type,
        building_key=building_key,
    )


def get_troop_stat_bonuses(manor, troop_key: str, tech_levels: Optional[Dict[str, int]] = None) -> Dict[str, float]:
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
    return get_tech_bonus(manor, "march_speed")


def get_building_cost_reduction(manor) -> float:
    return get_tech_bonus(manor, "building_cost_reduction")
