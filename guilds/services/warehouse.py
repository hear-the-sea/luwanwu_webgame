# guilds/services/warehouse.py

from django.db import transaction
from django.db.models import F

from gameplay.models import InventoryItem, Manor

from ..constants import DAILY_EXCHANGE_LIMIT
from ..models import GuildExchangeLog, GuildMember, GuildWarehouse


def add_item_to_warehouse(guild, item_key, quantity, contribution_cost):
    """
    添加物品到帮会仓库

    Args:
        guild: Guild对象
        item_key: 物品key
        quantity: 数量
        contribution_cost: 兑换成本（贡献度）
    """
    warehouse_item, created = GuildWarehouse.objects.get_or_create(
        guild=guild,
        item_key=item_key,
        defaults={'contribution_cost': contribution_cost}
    )

    # 使用 F() 表达式避免并发下读-改-写丢失更新
    GuildWarehouse.objects.filter(pk=warehouse_item.pk).update(
        quantity=F("quantity") + quantity,
        total_produced=F("total_produced") + quantity,
    )


def exchange_item(member, item_key, quantity=1):
    """
    兑换帮会仓库物品（并发安全版本 + 修复字段错误）

    使用数据库行锁和F()表达式确保并发安全：
    - 锁定GuildMember防止贡献度透支
    - 锁定GuildWarehouse防止物品超卖
    - 锁定InventoryItem防止物品发放时的并发冲突

    修复：将错误的 item_key 字段改为正确的 template 字段

    Args:
        member: GuildMember对象
        item_key: 物品key
        quantity: 兑换数量

    Raises:
        ValueError: 验证失败
    """
    from gameplay.models import ItemTemplate

    # 验证物品模板是否存在并可用
    try:
        template = ItemTemplate.objects.get(key=item_key)
        if not template.is_usable:
            raise ValueError("此物品不可在仓库使用")
    except ItemTemplate.DoesNotExist:
        raise ValueError("物品不存在")

    # 并发安全的事务处理
    # 锁定顺序：GuildMember -> GuildWarehouse -> InventoryItem
    with transaction.atomic():
        # 步骤1：锁定成员并验证兑换次数和贡献度
        member_locked = GuildMember.objects.select_for_update().get(pk=member.pk)

        # 重置每日限制（必须在锁内执行，避免并发下穿透每日上限）
        member_locked.reset_daily_limits()

        if member_locked.daily_exchange_count >= DAILY_EXCHANGE_LIMIT:
            raise ValueError(f"今日兑换次数已达上限（{DAILY_EXCHANGE_LIMIT}次）")

        # 步骤2：锁定仓库物品并验证库存
        warehouse_item = (
            GuildWarehouse.objects.select_for_update()
            .filter(guild=member_locked.guild, item_key=item_key)
            .first()
        )

        if not warehouse_item:
            raise ValueError("物品不存在")

        if warehouse_item.quantity < quantity:
            raise ValueError(f"库存不足，剩余{warehouse_item.quantity}件")

        # 计算总成本并验证贡献度
        total_cost = warehouse_item.contribution_cost * quantity
        if member_locked.current_contribution < total_cost:
            raise ValueError(f"贡献度不足，需要{total_cost}贡献")

        # 步骤3：使用F()表达式扣除贡献度和增加兑换次数
        updated_member = GuildMember.objects.filter(pk=member_locked.pk).update(
            current_contribution=F("current_contribution") - total_cost,
            daily_exchange_count=F("daily_exchange_count") + 1,
        )

        if not updated_member:
            raise ValueError("贡献度扣除失败，请重试")

        # 步骤4：使用F()表达式扣除仓库库存并记录兑换量
        # quantity__gte条件确保不会扣成负数
        updated_wh = GuildWarehouse.objects.filter(
            pk=warehouse_item.pk, quantity__gte=quantity
        ).update(
            quantity=F("quantity") - quantity,
            total_exchanged=F("total_exchanged") + quantity,
        )

        if not updated_wh:
            raise ValueError("库存不足，兑换失败")

        # 清理零库存记录
        warehouse_item.refresh_from_db()
        if warehouse_item.quantity == 0:
            warehouse_item.delete()

        # 步骤5：添加物品到玩家仓库
        # 修复：使用正确的template字段和StorageLocation枚举
        manor = Manor.objects.get(user=member_locked.user)

        # 锁定现有库存记录，防止并发冲突
        inventory_item = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=manor,
                template=template,  # 修复：使用template字段而不是item_key
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )

        if inventory_item:
            # 已有该物品，使用F()表达式增加数量
            InventoryItem.objects.filter(pk=inventory_item.pk).update(
                quantity=F("quantity") + quantity
            )
        else:
            # 首次获得该物品，创建新记录
            InventoryItem.objects.create(
                manor=manor,
                template=template,  # 修复：使用template字段
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity=quantity,
            )

        # 步骤6：记录兑换日志
        GuildExchangeLog.objects.create(
            guild=member_locked.guild,
            member=member_locked,
            item_key=item_key,
            quantity=quantity,
            contribution_cost=total_cost,
        )


def produce_equipment(guild, tech_level):
    """
    装备锻造科技产出装备

    Args:
        guild: Guild对象
        tech_level: 科技等级
    """
    # 根据等级确定产出
    production_table = {
        1: [('gear_green_random', 2, 50)],
        2: [('gear_green_random', 3, 50)],
        3: [('gear_blue_random', 2, 150)],
        4: [('gear_blue_random', 3, 150)],
        5: [('gear_purple_random', 1, 500)],
    }

    items = production_table.get(tech_level, [])
    for item_key, quantity, cost in items:
        # 这里简化处理，实际应该从ItemTemplate中随机选择装备
        add_item_to_warehouse(guild, item_key, quantity, cost)


def produce_experience_items(guild, tech_level):
    """
    经验炼制科技产出经验道具

    Args:
        guild: Guild对象
        tech_level: 科技等级
    """
    production_table = {
        1: [('exp_small', 3, 30)],
        2: [('exp_small', 5, 30)],
        3: [('exp_medium', 2, 100)],
        4: [('exp_medium', 3, 100)],
        5: [('exp_large', 1, 400)],
    }

    items = production_table.get(tech_level, [])
    for item_key, quantity, cost in items:
        add_item_to_warehouse(guild, item_key, quantity, cost)


def produce_resource_packs(guild, tech_level):
    """
    资源补给科技产出资源包

    Args:
        guild: Guild对象
        tech_level: 科技等级
    """
    production_table = {
        1: [('resource_pack_silver', 2, 20)],
        2: [('resource_pack_grain', 2, 20)],
        3: [('resource_pack_silver', 3, 30)],
        4: [('resource_pack_mixed', 2, 20)],
        5: [('resource_pack_advanced', 3, 80)],
    }

    items = production_table.get(tech_level, [])
    for item_key, quantity, cost in items:
        add_item_to_warehouse(guild, item_key, quantity, cost)


def get_warehouse_items(guild):
    """
    获取帮会仓库物品列表，附加ItemTemplate信息（N+1查询优化版本）

    性能优化：
    - 原实现：每个仓库物品执行1次ItemTemplate查询（N+1问题）
    - 优化后：批量预加载所有模板，总共2次查询

    Args:
        guild: Guild对象

    Returns:
        list: 包含仓库物品和ItemTemplate信息的字典列表
    """
    from gameplay.utils.template_loader import get_item_templates_by_keys

    # 查询1：获取所有仓库物品
    warehouse_items = list(
        GuildWarehouse.objects.filter(guild=guild, quantity__gt=0).order_by(
            '-contribution_cost', 'item_key'
        )
    )

    # 查询2：批量预加载所有需要的ItemTemplate，避免逐个查询
    item_keys = {item.item_key for item in warehouse_items}
    templates_dict = get_item_templates_by_keys(item_keys)

    # 在内存中关联模板信息
    result = []
    for item in warehouse_items:
        template = templates_dict.get(item.item_key)
        item.template = template
        # 如果找不到模板，默认可用（向后兼容）
        item.is_usable = template.is_usable if template else True
        result.append(item)

    return result


def get_exchange_logs(guild, limit=50):
    """
    获取兑换日志

    Args:
        guild: Guild对象
        limit: 返回数量

    Returns:
        QuerySet
    """
    return GuildExchangeLog.objects.filter(
        guild=guild
    ).select_related('member__user__manor').order_by('-exchanged_at')[:limit]
