"""
建筑配置服务模块

从 YAML 文件加载建筑配置，提供建筑描述等信息的查询接口。
"""

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml
from django.conf import settings


@lru_cache(maxsize=1)
def load_building_templates() -> Dict[str, Any]:
    """
    加载建筑配置文件。

    Returns:
        包含 categories 和 buildings 的字典
    """
    path = os.path.join(settings.BASE_DIR, "data", "building_templates.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _build_building_index() -> Dict[str, Dict[str, Any]]:
    """
    构建建筑索引字典，将 O(n) 查找优化为 O(1)。

    Returns:
        {building_key: building_config} 索引字典
    """
    data = load_building_templates()
    return {b["key"]: b for b in data.get("buildings", [])}


def get_building_config(key: str) -> Optional[Dict[str, Any]]:
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
    return config.get("description", "") if config else ""


def get_all_buildings() -> List[Dict[str, Any]]:
    """
    获取所有建筑配置列表。

    Returns:
        建筑配置列表
    """
    data = load_building_templates()
    return data.get("buildings", [])


def get_building_categories() -> List[Dict[str, Any]]:
    """
    获取建筑分类列表。

    Returns:
        分类配置列表
    """
    data = load_building_templates()
    return data.get("categories", [])


def get_buildings_by_category(category: str) -> List[Dict[str, Any]]:
    """
    获取指定分类的建筑列表。

    Args:
        category: 分类 key

    Returns:
        该分类下的建筑配置列表
    """
    return [b for b in get_all_buildings() if b.get("category") == category]


def clear_building_cache() -> None:
    """
    清除建筑配置缓存。

    在修改 YAML 文件后调用此函数以重新加载配置。
    """
    load_building_templates.cache_clear()
    _build_building_index.cache_clear()
