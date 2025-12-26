from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List

import yaml

from django.conf import settings

from gameplay.models import ItemTemplate


SHOP_CONFIG_PATH = settings.BASE_DIR / "data" / "shop_items.yaml"
BUY_PRICE_MULTIPLIER = 2  # 购买价 = 基准价 * 2


@dataclass
class ShopItemConfig:
    """商铺商品配置"""

    item_key: str
    price: int | None  # None 表示使用 ItemTemplate.price
    stock: int  # -1 表示无限
    daily_refresh: bool

    @property
    def is_unlimited(self) -> bool:
        return self.stock == -1


def load_shop_config() -> List[ShopItemConfig]:
    """加载商铺配置"""
    if not SHOP_CONFIG_PATH.exists():
        return []

    with open(SHOP_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    items = data.get("items") or []
    result = []

    for item in items:
        config = ShopItemConfig(
            item_key=item.get("item_key", ""),
            price=item.get("price"),
            stock=item.get("stock", -1),
            daily_refresh=item.get("daily_refresh", False),
        )
        if config.item_key:
            result.append(config)

    return result


@lru_cache(maxsize=1)
def _load_shop_config_cached() -> List[ShopItemConfig]:
    """缓存版本的配置加载"""
    return load_shop_config()


def get_shop_config() -> List[ShopItemConfig]:
    """获取商铺配置（带缓存）"""
    return _load_shop_config_cached()


def reload_shop_config() -> None:
    """重新加载配置（清除缓存）"""
    _load_shop_config_cached.cache_clear()


def get_shop_item_config(item_key: str) -> ShopItemConfig | None:
    """获取单个商品配置"""
    for config in get_shop_config():
        if config.item_key == item_key:
            return config
    return None


def get_base_price(item_key: str) -> int | None:
    """
    获取商品基准价格（即售出价格）
    优先使用 YAML 配置的价格，否则使用 ItemTemplate.price
    """
    config = get_shop_item_config(item_key)
    if config and config.price is not None:
        return config.price

    try:
        template = ItemTemplate.objects.get(key=item_key)
        return template.price
    except ItemTemplate.DoesNotExist:
        return None


def get_item_price(item_key: str) -> int | None:
    """
    获取商品购买价格 = 基准价 * BUY_PRICE_MULTIPLIER
    """
    base_price = get_base_price(item_key)
    if base_price is None:
        return None
    return int(base_price * BUY_PRICE_MULTIPLIER)


def get_sell_price(item_key: str) -> int:
    """
    获取物品回收价格（即基准价格）
    """
    base_price = get_base_price(item_key)
    if base_price is None:
        return 0
    return base_price


def get_sell_price_by_template(template: ItemTemplate) -> int:
    """
    根据 ItemTemplate 获取回收价格（即基准价格）
    """
    config = get_shop_item_config(template.key)
    if config and config.price is not None:
        return config.price
    return template.price
