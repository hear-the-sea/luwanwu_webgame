"""
拍卖行配置加载服务

提供YAML配置文件的加载和缓存功能，参考 shop_config.py 的实现模式。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional

import yaml
from django.conf import settings

AUCTION_CONFIG_PATH = settings.BASE_DIR / "data" / "auction_items.yaml"


@dataclass
class AuctionSettings:
    """拍卖行全局设置"""

    cycle_days: int  # 拍卖周期（天）
    min_increment_ratio: float  # 最小加价幅度比例
    default_min_increment: int  # 默认最小加价幅度


@dataclass
class AuctionItemConfig:
    """拍卖商品配置"""

    item_key: str
    slots: int  # 拆分成多少个独立拍卖位
    quantity_per_slot: int  # 每个拍卖位的物品数量
    starting_price: int  # 起拍价（金条）
    min_increment: int  # 最小加价幅度（金条）
    enabled: bool  # 是否启用


@dataclass
class AuctionConfig:
    """拍卖行完整配置"""

    settings: AuctionSettings
    items: List[AuctionItemConfig]


def load_auction_config() -> AuctionConfig:
    """加载拍卖行配置"""
    default_settings = AuctionSettings(
        cycle_days=3,
        min_increment_ratio=0.1,
        default_min_increment=1,
    )

    if not AUCTION_CONFIG_PATH.exists():
        return AuctionConfig(settings=default_settings, items=[])

    with open(AUCTION_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 解析全局设置
    settings_data = data.get("settings") or {}
    auction_settings = AuctionSettings(
        cycle_days=settings_data.get("cycle_days", 3),
        min_increment_ratio=settings_data.get("min_increment_ratio", 0.1),
        default_min_increment=settings_data.get("default_min_increment", 1),
    )

    # 解析商品列表
    items_data = data.get("items") or []
    items = []

    for item in items_data:
        item_key = item.get("item_key", "")
        if not item_key:
            continue

        config = AuctionItemConfig(
            item_key=item_key,
            slots=item.get("slots", 1),
            quantity_per_slot=item.get("quantity_per_slot", 1),
            starting_price=item.get("starting_price", 1),
            min_increment=item.get("min_increment", auction_settings.default_min_increment),
            enabled=item.get("enabled", True),
        )
        items.append(config)

    return AuctionConfig(settings=auction_settings, items=items)


@lru_cache(maxsize=1)
def _load_auction_config_cached() -> AuctionConfig:
    """缓存版本的配置加载"""
    return load_auction_config()


def get_auction_config() -> AuctionConfig:
    """获取拍卖行配置（带缓存）"""
    return _load_auction_config_cached()


def reload_auction_config() -> None:
    """重新加载配置（清除缓存）"""
    _load_auction_config_cached.cache_clear()


def get_auction_settings() -> AuctionSettings:
    """获取拍卖行全局设置"""
    return get_auction_config().settings


def get_enabled_auction_items() -> List[AuctionItemConfig]:
    """获取启用的拍卖商品列表"""
    return [item for item in get_auction_config().items if item.enabled]


def get_auction_item_config(item_key: str) -> Optional[AuctionItemConfig]:
    """获取单个拍卖商品配置"""
    for item in get_auction_config().items:
        if item.item_key == item_key:
            return item
    return None
