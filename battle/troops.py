from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import yaml
from django.conf import settings
from django.core.cache import cache

DEFAULT_TROOP_FILE = Path(settings.BASE_DIR) / "data" / "troop_templates.yaml"

# 兵种模板缓存键和过期时间
TROOP_TEMPLATES_CACHE_KEY = "troop_templates:db"
TROOP_TEMPLATES_CACHE_TIMEOUT = 300  # 5分钟


def load_troop_templates_from_db() -> Dict[str, dict]:
    """
    从数据库加载兵种模板（使用缓存）

    Returns:
        兵种模板字典 {key: data}
    """
    # 尝试从缓存获取
    templates = cache.get(TROOP_TEMPLATES_CACHE_KEY)
    if templates is not None:
        return templates

    from battle.models import TroopTemplate

    templates = {}
    for troop in TroopTemplate.objects.all():
        templates[troop.key] = {
            "label": troop.name,
            "description": troop.description,
            "base_attack": troop.base_attack,
            "base_defense": troop.base_defense,
            "base_hp": troop.base_hp,
            "speed_bonus": troop.speed_bonus,
            "priority": troop.priority,
            "default_count": troop.default_count,
            "avatar": troop.avatar.url if troop.avatar else None,
        }

    # 只有数据库有数据时才缓存
    if templates:
        cache.set(TROOP_TEMPLATES_CACHE_KEY, templates, timeout=TROOP_TEMPLATES_CACHE_TIMEOUT)

    return templates


def invalidate_troop_templates_cache() -> None:
    """
    清除兵种模板缓存（在 TroopTemplate 变更或 YAML 更新时调用）
    """
    cache.delete(TROOP_TEMPLATES_CACHE_KEY)
    try:
        load_troop_templates_from_yaml.cache_clear()
    except Exception:
        # Best-effort: cache_clear may fail in edge cases (e.g. during reload)
        pass


@lru_cache()
def load_troop_templates_from_yaml(file_path: str | None = None) -> Dict[str, dict]:
    """
    从 YAML 文件加载兵种模板（回退方案）

    Args:
        file_path: YAML文件路径

    Returns:
        兵种模板字典 {key: data}
    """
    path = Path(file_path or DEFAULT_TROOP_FILE)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    templates = {}
    for item in data.get("troops", []):
        key = item["key"]
        templates[key] = {
            "label": item.get("name", key),
            "description": item.get("description", ""),
            "base_attack": item.get("base_attack", 30),
            "base_defense": item.get("base_defense", 20),
            "base_hp": item.get("base_hp", 80),
            "speed_bonus": item.get("speed_bonus", 10),
            "priority": int(item.get("priority", 0)),
            "default_count": int(item.get("default_count", 120)),
            "avatar": None,
        }
    return templates


def load_troop_templates(file_path: str | None = None) -> Dict[str, dict]:
    """
    加载兵种模板（优先从数据库，否则从YAML）

    Args:
        file_path: YAML文件路径（回退方案使用）

    Returns:
        兵种模板字典 {key: data}
    """
    # 优先从数据库加载
    templates = load_troop_templates_from_db()

    # 如果数据库为空，从YAML加载
    if not templates:
        templates = load_troop_templates_from_yaml(file_path)

    return templates


def troop_template_list() -> List[dict]:
    templates = load_troop_templates()
    return [
        {"key": key, **value}
        for key, value in sorted(templates.items(), key=lambda item: item[1]["priority"])
    ]


def default_troop_loadout() -> Dict[str, int]:
    templates = load_troop_templates()
    loadout = {}
    for key, data in templates.items():
        loadout[key] = int(data.get("default_count", 120))
    return loadout
