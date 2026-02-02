"""
帮会仓库科技产出配置加载器

将产出配置从代码中提取到 YAML 文件，便于维护和调整。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List

import yaml

from django.conf import settings


WAREHOUSE_PRODUCTION_PATH = settings.BASE_DIR / "data" / "warehouse_production.yaml"


@dataclass
class ProductionItem:
    """单个产出物品配置"""

    item_key: str
    quantity: int
    contribution_cost: int


@dataclass
class TechProduction:
    """科技产出配置"""

    tech_key: str
    levels: Dict[int, List[ProductionItem]]

    def get_items(self, level: int) -> List[ProductionItem]:
        """获取指定等级的产出物品列表"""
        return self.levels.get(level, [])


def load_warehouse_production() -> Dict[str, TechProduction]:
    """加载仓库产出配置"""
    if not WAREHOUSE_PRODUCTION_PATH.exists():
        return {}

    with open(WAREHOUSE_PRODUCTION_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    result = {}

    for tech_key, tech_data in data.items():
        levels_data = tech_data.get("levels", {})
        levels = {}

        for level, items in levels_data.items():
            level_int = int(level)
            levels[level_int] = [
                ProductionItem(
                    item_key=item.get("item_key", ""),
                    quantity=item.get("quantity", 1),
                    contribution_cost=item.get("contribution_cost", 0),
                )
                for item in items
                if item.get("item_key")
            ]

        result[tech_key] = TechProduction(tech_key=tech_key, levels=levels)

    return result


@lru_cache(maxsize=1)
def _load_warehouse_production_cached() -> Dict[str, TechProduction]:
    """缓存版本的配置加载"""
    return load_warehouse_production()


def get_warehouse_production() -> Dict[str, TechProduction]:
    """获取仓库产出配置（带缓存）"""
    return _load_warehouse_production_cached()


def reload_warehouse_production() -> None:
    """重新加载配置（清除缓存）"""
    _load_warehouse_production_cached.cache_clear()


def get_tech_production(tech_key: str) -> TechProduction | None:
    """获取指定科技的产出配置"""
    return get_warehouse_production().get(tech_key)


def get_production_items(tech_key: str, level: int) -> List[ProductionItem]:
    """获取指定科技指定等级的产出物品列表"""
    tech = get_tech_production(tech_key)
    if tech:
        return tech.get_items(level)
    return []
