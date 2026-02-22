"""
建筑配置服务模块

从 YAML 文件加载建筑配置，提供建筑描述等信息的查询接口。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from django.conf import settings

from core.utils.yaml_loader import ensure_list, ensure_mapping, load_yaml_data

logger = logging.getLogger(__name__)
BUILDING_TEMPLATES_PATH = settings.BASE_DIR / "data" / "building_templates.yaml"


def _normalize_building_entries(raw: Any) -> list[dict[str, Any]]:
    entries = ensure_list(raw, logger=logger, context="building templates buildings")
    buildings: list[dict[str, Any]] = []
    for row in entries:
        item = ensure_mapping(row, logger=logger, context="building templates building row")
        if not item:
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        normalized = dict(item)
        normalized["key"] = key
        buildings.append(normalized)
    return buildings


def _normalize_category_entries(raw: Any) -> list[dict[str, Any]]:
    entries = ensure_list(raw, logger=logger, context="building templates categories")
    categories: list[dict[str, Any]] = []
    for row in entries:
        item = ensure_mapping(row, logger=logger, context="building templates category row")
        if not item:
            continue
        normalized = dict(item)
        key = str(normalized.get("key") or "").strip()
        if key:
            normalized["key"] = key
        categories.append(normalized)
    return categories


@lru_cache(maxsize=1)
def load_building_templates() -> dict[str, Any]:
    """
    加载建筑配置文件。

    Returns:
        包含 categories 和 buildings 的字典
    """
    raw = load_yaml_data(
        BUILDING_TEMPLATES_PATH,
        logger=logger,
        context="building templates",
        default={},
    )
    payload = ensure_mapping(raw, logger=logger, context="building templates root")
    return {
        "categories": _normalize_category_entries(payload.get("categories")),
        "buildings": _normalize_building_entries(payload.get("buildings")),
    }


@lru_cache(maxsize=1)
def _build_building_index() -> dict[str, dict[str, Any]]:
    """
    构建建筑索引字典，将 O(n) 查找优化为 O(1)。

    Returns:
        {building_key: building_config} 索引字典
    """
    data = load_building_templates()
    buildings = ensure_list(data.get("buildings"), logger=logger, context="building templates buildings")
    result: dict[str, dict[str, Any]] = {}
    for row in buildings:
        item = ensure_mapping(row, logger=logger, context="building templates building row")
        if not item:
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        result[key] = item
    return result


def get_building_config(key: str) -> dict[str, Any] | None:
    """
    获取指定建筑的配置。

    Args:
        key: 建筑 key

    Returns:
        建筑配置字典，不存在则返回 None
    """
    return _build_building_index().get(key)


def get_building_description(key: str) -> str:
    """
    获取建筑描述。

    Args:
        key: 建筑 key

    Returns:
        建筑描述文本，不存在则返回空字符串
    """
    config = get_building_config(key)
    if not config:
        return ""
    return str(config.get("description") or "")


def get_all_buildings() -> list[dict[str, Any]]:
    """
    获取所有建筑配置列表。

    Returns:
        建筑配置列表
    """
    data = load_building_templates()
    return _normalize_building_entries(data.get("buildings"))


def get_building_categories() -> list[dict[str, Any]]:
    """
    获取建筑分类列表。

    Returns:
        分类配置列表
    """
    data = load_building_templates()
    return _normalize_category_entries(data.get("categories"))


def get_buildings_by_category(category: str) -> list[dict[str, Any]]:
    """
    获取指定分类的建筑列表。

    Args:
        category: 分类 key

    Returns:
        该分类下的建筑配置列表
    """
    category_key = str(category or "")
    return [b for b in get_all_buildings() if str(b.get("category") or "") == category_key]


def clear_building_cache() -> None:
    """
    清除建筑配置缓存。

    在修改 YAML 文件后调用此函数以重新加载配置。
    """
    load_building_templates.cache_clear()
    _build_building_index.cache_clear()
