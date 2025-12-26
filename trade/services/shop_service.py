"""
商铺交易服务
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from django.db import transaction
from django.db.models import F

from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from gameplay.services.resources import grant_resources, spend_resources
from gameplay.utils.template_loader import get_item_templates_by_keys

from ..models import ShopPurchaseLog, ShopSellLog, ShopStock
from .shop_config import (
    get_sell_price_by_template,
    get_shop_config,
    get_shop_item_config,
)


@dataclass
class ShopItemDisplay:
    """商铺商品展示数据"""

    key: str
    name: str
    description: str
    price: int
    stock: int  # -1 表示无限
    stock_display: str
    available: bool  # 是否可购买
    icon: str  # 图标
    image_url: str  # 图片 URL
    effect_type: str  # 效果类型
    category: str  # 种类显示名称
    rarity: str  # 稀有度
    effect_payload: dict  # 效果数据（装备属性、套装等）


@dataclass
class SellableItemDisplay:
    """可出售物品展示数据"""

    inventory_item: InventoryItem
    sell_price: int


# 效果类型到种类名称的映射
EFFECT_TYPE_CATEGORY = {
    "resource_pack": "资源",
    "skill_book": "技能书",
    "experience_items": "经验",
    "medicine": "药品",
    "tool": "道具",
    "equip_helmet": "头盔",
    "equip_armor": "衣服",
    "equip_shoes": "鞋子",
    "equip_weapon": "武器",
    "equip_mount": "坐骑",
    "equip_ornament": "饰品",
    "equip_device": "器械",
}


def _normalize_effect_type(effect_type: str) -> str:
    """统一工具类 effect_type，兼容旧数据。"""
    if effect_type in {"magnifying_glass", "peace_shield", "manor_rename"}:
        return ItemTemplate.EffectType.TOOL
    return effect_type


def _get_category(effect_type: str) -> str:
    """获取种类显示名称"""
    effect_type = _normalize_effect_type(effect_type)
    if effect_type.startswith("equip_"):
        return EFFECT_TYPE_CATEGORY.get(effect_type, "装备")
    return EFFECT_TYPE_CATEGORY.get(effect_type, "其他")


def get_shop_items_for_display() -> List[ShopItemDisplay]:
    """
    获取商铺商品列表（用于页面展示）
    """
    config_list = get_shop_config()
    if not config_list:
        return []

    # 批量获取 ItemTemplate
    item_keys = [c.item_key for c in config_list]
    templates = get_item_templates_by_keys(item_keys)

    # 批量获取库存
    stocks = {s.item_key: s.current_stock for s in ShopStock.objects.filter(item_key__in=item_keys)}

    result = []
    for config in config_list:
        template = templates.get(config.item_key)
        if not template:
            continue

        # 确定价格
        price = config.price if config.price is not None else template.price

        # 确定库存
        if config.is_unlimited:
            stock = -1
            stock_display = "无限"
            available = True
        else:
            # 有限库存：从数据库获取当前库存，如果不存在则使用配置的初始值
            current_stock = stocks.get(config.item_key, config.stock)
            stock = current_stock
            stock_display = str(current_stock)
            available = current_stock > 0

        result.append(
            ShopItemDisplay(
                key=template.key,
                name=template.name,
                description=template.description,
                price=price,
                stock=stock,
                stock_display=stock_display,
                available=available,
                icon=template.icon or "",
                image_url=template.image.url if template.image else "",
                effect_type=_normalize_effect_type(template.effect_type or ""),
                category=_get_category(template.effect_type or ""),
                rarity=template.rarity or "black",
                effect_payload=template.effect_payload or {},
            )
        )

    return result


def get_sellable_inventory(manor: Manor) -> List[SellableItemDisplay]:
    """
    获取玩家可出售的物品列表

    IMPORTANT: Only show WAREHOUSE items since sell_item only operates on WAREHOUSE.
    """
    items = manor.inventory_items.select_related("template").filter(
        quantity__gt=0,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE
    )
    result = []

    for item in items:
        sell_price = get_sell_price_by_template(item.template)
        if sell_price > 0:  # 只显示有回收价的物品
            result.append(SellableItemDisplay(inventory_item=item, sell_price=sell_price))

    return result


@transaction.atomic
def buy_item(manor: Manor, item_key: str, quantity: int) -> Dict:
    """
    购买商品

    Lock order: ShopStock -> Manor (via spend_resources) -> InventoryItem
    All code paths must acquire locks in this order to prevent deadlocks.

    Args:
        manor: 庄园对象
        item_key: 商品 key
        quantity: 购买数量

    Returns:
        购买结果字典

    Raises:
        ValueError: 购买失败时抛出
    """
    if quantity <= 0:
        raise ValueError("购买数量必须大于 0")

    # 检查商品配置
    config = get_shop_item_config(item_key)
    if config is None:
        raise ValueError("商品不存在")

    # 获取物品模板
    try:
        template = ItemTemplate.objects.get(key=item_key)
    except ItemTemplate.DoesNotExist:
        raise ValueError("商品不存在")

    # 确定价格
    unit_price = config.price if config.price is not None else template.price
    total_cost = unit_price * quantity

    # 检查库存（使用行级锁防止超卖）
    if not config.is_unlimited:
        stock, created = ShopStock.objects.select_for_update().get_or_create(
            item_key=item_key, defaults={"current_stock": config.stock}
        )
        if stock.current_stock < quantity:
            raise ValueError("库存不足")

    # 检查并扣除银两
    spend_resources(
        manor,
        {"silver": total_cost},
        f"购买 {template.name} x{quantity}",
        ResourceEvent.Reason.SHOP_PURCHASE,
    )

    # 扣除库存（原子操作，防止并发超卖）
    if not config.is_unlimited:
        # Use atomic update with validation to prevent race conditions
        updated = ShopStock.objects.filter(
            pk=stock.pk, current_stock__gte=quantity
        ).update(current_stock=F("current_stock") - quantity)
        if not updated:
            raise ValueError("库存不足")

    # 添加物品到背包（原子操作，防止并发丢失更新）
    # IMPORTANT: Must specify storage_location to avoid MultipleObjectsReturned
    # when the same template exists in both warehouse and treasury
    inventory_item, created = InventoryItem.objects.select_for_update().get_or_create(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": 0}
    )
    # Use atomic F() expression to increment quantity
    InventoryItem.objects.filter(pk=inventory_item.pk).update(
        quantity=F("quantity") + quantity
    )

    # 记录购买日志
    ShopPurchaseLog.objects.create(
        manor=manor,
        item_key=item_key,
        quantity=quantity,
        unit_price=unit_price,
        total_cost=total_cost,
    )

    return {
        "item_name": template.name,
        "quantity": quantity,
        "total_cost": total_cost,
    }


@transaction.atomic
def sell_item(manor: Manor, item_key: str, quantity: int) -> Dict:
    """
    出售物品

    Lock order: Manor (via grant_resources) -> InventoryItem
    Matches buy_item lock order to prevent deadlocks.

    Args:
        manor: 庄园对象
        item_key: 物品 key
        quantity: 出售数量

    Returns:
        出售结果字典

    Raises:
        ValueError: 出售失败时抛出
    """
    if quantity <= 0:
        raise ValueError("出售数量必须大于 0")

    # 获取物品模板
    try:
        template = ItemTemplate.objects.get(key=item_key)
    except ItemTemplate.DoesNotExist:
        raise ValueError("物品不存在")

    # 获取背包物品（不使用 select_for_update 以避免锁顺序问题）
    # IMPORTANT: Must specify storage_location to avoid MultipleObjectsReturned
    # when the same template exists in both warehouse and treasury
    try:
        inventory_item = InventoryItem.objects.get(
            manor=manor,
            template=template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE
        )
    except InventoryItem.DoesNotExist:
        raise ValueError("您没有该物品")

    if inventory_item.quantity < quantity:
        raise ValueError("物品数量不足")

    # 计算回收价
    unit_price = get_sell_price_by_template(template)
    if unit_price <= 0:
        raise ValueError("该物品无法出售")

    total_income = unit_price * quantity

    # 发放银两（先锁 Manor，保持与 buy_item 相同的锁顺序）
    grant_resources(
        manor,
        {"silver": total_income},
        f"出售 {template.name} x{quantity}",
        ResourceEvent.Reason.SHOP_SELL,
    )

    # 扣除背包物品（使用原子操作，在 Manor 锁之后）
    # Use atomic F() expression to prevent race conditions
    updated = InventoryItem.objects.filter(
        pk=inventory_item.pk, quantity__gte=quantity
    ).update(quantity=F("quantity") - quantity)
    if not updated:
        raise ValueError("物品数量不足")

    # 清理库存为 0 的物品
    InventoryItem.objects.filter(pk=inventory_item.pk, quantity=0).delete()

    # 记录出售日志
    ShopSellLog.objects.create(
        manor=manor,
        item_key=item_key,
        quantity=quantity,
        unit_price=unit_price,
        total_income=total_income,
    )

    return {
        "item_name": template.name,
        "quantity": quantity,
        "total_income": total_income,
    }
