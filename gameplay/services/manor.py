"""
庄园和建筑管理服务
"""

from __future__ import annotations

import logging
import math
import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from datetime import datetime

from django.utils import timezone

from core.utils.time_scale import scale_duration

from ..constants import BuildingKeys, MAX_CONCURRENT_BUILDING_UPGRADES, BUILDING_MAX_LEVELS, ManorNameConstants
from ..models import Building, BuildingType, Manor, Message, ResourceEvent
from .notifications import notify_user
from .cache import invalidate_home_stats_cache


# 银库/粮仓容量计算参数
CAPACITY_BASE = 20000  # 1级容量
CAPACITY_GROWTH_SILVER = 1.299657  # 银库增长系数，30级达到4000万
CAPACITY_GROWTH_GRAIN = 1.3905  # 粮仓增长系数，20级达到约1050万


def calculate_building_capacity(level: int, is_silver_vault: bool = False) -> int:
    """
    计算银库或粮仓的容量。

    银库：1级: 20,000  30级: 40,000,000
    粮仓：1级: 20,000  20级: 10,500,000
    公式: base * (growth ^ (level - 1))
    """
    growth = CAPACITY_GROWTH_SILVER if is_silver_vault else CAPACITY_GROWTH_GRAIN
    return int(CAPACITY_BASE * (growth ** (level - 1)))


logger = logging.getLogger(__name__)


def ensure_manor(user, region: str = "overseas") -> Manor:
    """
    获取或创建用户的庄园，确保庄园拥有所有建筑。

    Args:
        user: 用户对象
        region: 地区编码（仅在创建时使用）

    Returns:
        庄园对象
    """
    manor, created = Manor.objects.get_or_create(user=user)
    if created:
        # First persist the record (already created by get_or_create), then
        # assign a unique coordinate under a transaction to avoid races.
        from ..constants import PVPConstants

        assigned = False
        for _ in range(5):
            x, y = generate_unique_coordinate(region)
            try:
                with transaction.atomic():
                    locked = Manor.objects.select_for_update().get(pk=manor.pk)
                    locked.region = region
                    locked.coordinate_x = x
                    locked.coordinate_y = y
                    locked.newbie_protection_until = timezone.now() + timedelta(days=PVPConstants.NEWBIE_PROTECTION_DAYS)
                    locked.save(update_fields=["region", "coordinate_x", "coordinate_y", "newbie_protection_until"])
                manor.region = region
                manor.coordinate_x = x
                manor.coordinate_y = y
                manor.newbie_protection_until = locked.newbie_protection_until
                assigned = True
                break
            except IntegrityError:
                # Retry on unique constraint conflicts.
                continue

        if not assigned:
            raise RuntimeError("Failed to allocate a unique manor coordinate after multiple attempts")
        bootstrap_buildings(manor)
    else:
        ensure_buildings_exist(manor)
    return manor


def generate_unique_coordinate(region: str) -> tuple[int, int]:
    """
    为指定地区生成唯一坐标。

    Args:
        region: 地区编码

    Returns:
        (x, y) 坐标元组
    """
    import random
    from ..constants import PVPConstants

    # Generate a handful of candidates and check them in a single query.
    # This reduces DB round-trips compared to `exists()` in a tight loop.
    for _ in range(10):
        candidates: list[tuple[int, int]] = []
        for __ in range(20):
            candidates.append(
                (
                    random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX),
                    random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX),
                )
            )
        occupied = set(
            Manor.objects.filter(
                region=region,
                coordinate_x__in=[x for x, _ in candidates],
                coordinate_y__in=[y for _, y in candidates],
            ).values_list("coordinate_x", "coordinate_y")
        )
        for x, y in candidates:
            if (x, y) not in occupied:
                return x, y

    # Fallback: in extremely dense regions, fall back to the original approach.
    max_attempts = 200
    for _ in range(max_attempts):
        x = random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX)
        y = random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX)
        if not Manor.objects.filter(region=region, coordinate_x=x, coordinate_y=y).exists():
            return x, y

    logger.warning("Failed to find a unique coordinate for region=%s; using random fallback", region)
    return random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX), random.randint(
        PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX
    )


def bootstrap_buildings(manor: Manor) -> None:
    """
    为新建庄园初始化所有建筑。

    Args:
        manor: 庄园对象
    """
    building_types = list(BuildingType.objects.all())
    buildings_to_create = [
        Building(manor=manor, building_type=bt)
        for bt in building_types
    ]
    Building.objects.bulk_create(buildings_to_create, ignore_conflicts=True)


def ensure_buildings_exist(manor: Manor) -> None:
    """
    确保庄园拥有所有建筑类型，补充缺失的建筑。

    Args:
        manor: 庄园对象
    """
    existing = set(manor.buildings.values_list("building_type_id", flat=True))
    missing = list(BuildingType.objects.exclude(id__in=existing))
    if missing:
        buildings_to_create = [
            Building(manor=manor, building_type=bt)
            for bt in missing
        ]
        Building.objects.bulk_create(buildings_to_create)


def refresh_manor_state(manor: Manor) -> None:
    """
    刷新庄园状态：完成建筑升级、同步资源产出、刷新任务状态。

    Args:
        manor: 庄园对象
    """
    min_interval = getattr(settings, "MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS", 0)
    if min_interval > 0:
        cache_key = f"manor:refresh:{manor.pk}"
        try:
            if not cache.add(cache_key, "1", timeout=min_interval):
                return
        except Exception as e:
            # 缓存操作失败时记录日志，但继续执行刷新逻辑
            logger.warning(f"缓存操作失败，跳过频率限制检查: {e}")

    finalize_upgrades(manor)
    from .resources import sync_resource_production

    sync_resource_production(manor)
    from .missions import refresh_mission_runs

    refresh_mission_runs(manor)


def finalize_building_upgrade(
    building: Building, now: datetime | None = None, send_notification: bool = True
) -> bool:
    """
    完成单个建筑的升级（如果已到达完成时间）。

    Args:
        building: 建筑对象
        now: 当前时间（可选）
        send_notification: 是否发送通知

    Returns:
        是否成功完成升级（幂等：如果没有变化返回 False）
    """
    now = now or timezone.now()
    if not building.pk:
        return False

    # Do not rely on the in-memory object for idempotency: callers may hold stale instances.
    updated = (
        Building.objects.filter(
            pk=building.pk,
            is_upgrading=True,
            upgrade_complete_at__isnull=False,
            upgrade_complete_at__lte=now,
        ).update(
            level=F("level") + 1,
            is_upgrading=False,
            upgrade_complete_at=None,
        )
    )
    if updated != 1:
        return False

    building = Building.objects.select_related("manor", "building_type").get(pk=building.pk)

    # 银库/粮仓升级时更新容量字段
    building_key = building.building_type.key
    if building_key == BuildingKeys.SILVER_VAULT:
        new_capacity = calculate_building_capacity(building.level, is_silver_vault=True)
        Manor.objects.filter(pk=building.manor_id).update(silver_capacity=new_capacity)
    elif building_key == BuildingKeys.GRANARY:
        new_capacity = calculate_building_capacity(building.level, is_silver_vault=False)
        Manor.objects.filter(pk=building.manor_id).update(grain_capacity=new_capacity)

    # 使庄园建筑等级缓存失效，确保下次访问时重新加载
    building.manor.invalidate_building_cache()
    invalidate_home_stats_cache(building.manor_id)
    if send_notification:
        from .messages import create_message

        create_message(
            manor=building.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{building.building_type.name} 升级完成",
            body=f"等级 Lv{building.level - 1} → Lv{building.level}",
        )
        notify_user(
            building.manor.user_id,
            {
                "kind": "system",
                "title": f"{building.building_type.name} 升级完成",
                "building_key": building.building_type.key,
                "level": building.level,
            },
            log_context="building upgrade notification",
        )
    return True


def finalize_upgrades(manor: Manor, now: datetime | None = None) -> None:
    """
    完成庄园所有到期的建筑升级。

    Args:
        manor: 庄园对象
        now: 当前时间（可选）
    """
    now = now or timezone.now()
    ready = list(
        manor.buildings.select_related("building_type")
        .filter(is_upgrading=True, upgrade_complete_at__lte=now)
    )
    if not ready:
        return
    for building in ready:
        finalize_building_upgrade(building, now=now, send_notification=True)


def schedule_building_completion(building: Building, eta_seconds: int) -> None:
    """
    调度后台任务，在建筑升级计时器结束时完成升级。

    Args:
        building: 建筑对象
        eta_seconds: 预计完成时间（秒）
    """
    countdown = max(0, int(eta_seconds))
    try:
        from gameplay.tasks import complete_building_upgrade
    except Exception:
        logger.warning("Unable to import complete_building_upgrade task; skip scheduling", exc_info=True)
        return
    transaction.on_commit(lambda: complete_building_upgrade.apply_async(args=[building.id], countdown=countdown))


@transaction.atomic
def start_upgrade(building: Building) -> None:
    """
    开始建筑升级，消耗资源并设置升级计时器。

    支持建筑学科技减免：实际成本 = 基础成本 × (1 - 减免比例)

    Args:
        building: 建筑对象

    Raises:
        ValueError: 建筑正在升级中或资源不足时抛出
    """
    from .technology import get_building_cost_reduction

    manor = building.manor

    # 锁住庄园行，确保"升级并发上限"校验在并发请求下仍然可靠
    manor = Manor.objects.select_for_update().get(pk=manor.pk)

    # 安全修复：同时锁定建筑行，防止同一建筑并发升级
    # 避免 TOCTOU 漏洞：两个请求同时通过 is_upgrading 检查导致重复扣费
    building = Building.objects.select_for_update().get(pk=building.pk)
    if building.is_upgrading:
        raise ValueError("建筑正在升级中")

    # 检查建筑是否已达到最大等级
    building_key = building.building_type.key
    max_level = BUILDING_MAX_LEVELS.get(building_key)
    if max_level is not None and building.level >= max_level:
        raise ValueError(f"{building.building_type.name}已达到最大等级（Lv{max_level}）")

    upgrading_count = Building.objects.filter(manor=manor, is_upgrading=True).count()
    if upgrading_count >= MAX_CONCURRENT_BUILDING_UPGRADES:
        raise ValueError(f"同时最多只能升级 {MAX_CONCURRENT_BUILDING_UPGRADES} 个建筑")

    # 计算基础成本
    base_cost = building.next_level_cost()

    # 应用建筑学科技减免
    cost_reduction = get_building_cost_reduction(manor)
    reduction_multiplier = max(0, 1 - cost_reduction)  # 确保不会变成负数

    # 计算实际成本（向上取整，至少为1）
    cost = {
        resource: max(1, math.ceil(amount * reduction_multiplier))
        for resource, amount in base_cost.items()
    }

    from .resources import spend_resources_locked
    spend_resources_locked(manor, cost, building.building_type.name, ResourceEvent.Reason.UPGRADE_COST)

    # 累计银两花费，计算声望
    silver_spent = cost.get("silver", 0)
    if silver_spent > 0:
        from .prestige import add_prestige_silver_locked
        add_prestige_silver_locked(manor, silver_spent)

    # 计算基础升级时间
    base_duration = building.next_level_duration()

    # 应用祠堂建筑时间减少加成
    time_reduction = manor.citang_building_time_reduction
    duration_seconds = max(1, int(base_duration * (1 - time_reduction)))
    duration_seconds = scale_duration(duration_seconds, minimum=1)

    building.upgrade_complete_at = timezone.now() + timedelta(seconds=duration_seconds)
    building.is_upgrading = True
    building.save(update_fields=["upgrade_complete_at", "is_upgrading"])
    schedule_building_completion(building, duration_seconds)


# ============ 庄园命名服务 ============

# 庄园名称验证参数（使用常量类）
MANOR_NAME_MIN_LENGTH = ManorNameConstants.MIN_LENGTH
MANOR_NAME_MAX_LENGTH = ManorNameConstants.MAX_LENGTH
MANOR_NAME_PATTERN = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_]+$')

# 敏感词列表（从常量类获取）
BANNED_WORDS = ManorNameConstants.BANNED_WORDS


def validate_manor_name(name: str) -> tuple[bool, str]:
    """
    校验庄园名称是否合法。

    规则：
    - 长度：2-12 个字符
    - 仅允许中文、英文、数字、下划线
    - 不得包含敏感词

    Args:
        name: 待校验的名称

    Returns:
        (是否合法, 错误信息)
    """
    if not name or not name.strip():
        return False, "名称不能为空"

    name = name.strip()

    if len(name) < MANOR_NAME_MIN_LENGTH:
        return False, f"名称至少需要{MANOR_NAME_MIN_LENGTH}个字符"

    if len(name) > MANOR_NAME_MAX_LENGTH:
        return False, f"名称最多{MANOR_NAME_MAX_LENGTH}个字符"

    if not MANOR_NAME_PATTERN.match(name):
        return False, "名称仅支持中文、英文、数字和下划线"

    name_lower = name.lower()
    for word in BANNED_WORDS:
        if word.lower() in name_lower:
            return False, "名称包含敏感词"

    return True, ""


def is_manor_name_available(name: str, exclude_manor_id: int | None = None) -> bool:
    """
    检查庄园名称是否可用（未被占用）。

    Args:
        name: 待检查的名称
        exclude_manor_id: 排除的庄园 ID（用于改名时排除自己）

    Returns:
        名称是否可用
    """
    queryset = Manor.objects.filter(name__iexact=name.strip())
    if exclude_manor_id:
        queryset = queryset.exclude(id=exclude_manor_id)
    return not queryset.exists()


@transaction.atomic
def rename_manor(manor: Manor, new_name: str, consume_item: bool = True) -> None:
    """
    为庄园更名。

    Args:
        manor: 庄园对象
        new_name: 新名称
        consume_item: 是否消耗命名卡道具

    Raises:
        ValueError: 名称不合法、已被占用或无命名卡时抛出
    """
    from ..models import InventoryItem, ItemTemplate

    new_name = new_name.strip()

    # 校验名称格式
    valid, error_msg = validate_manor_name(new_name)
    if not valid:
        raise ValueError(error_msg)

    # 检查名称是否可用
    if not is_manor_name_available(new_name, exclude_manor_id=manor.id):
        raise ValueError("该名称已被使用")

    # 消耗命名卡道具
    if consume_item:
        try:
            rename_card = ItemTemplate.objects.get(key='manor_rename_card')
        except ItemTemplate.DoesNotExist:
            raise ValueError("庄园命名卡道具未配置")

        # 安全修复：使用 select_for_update 防止并发消耗
        inventory_item = InventoryItem.objects.select_for_update().filter(
            manor=manor,
            template=rename_card,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            quantity__gt=0,
        ).first()

        if not inventory_item:
            raise ValueError("您没有庄园命名卡")

        # 安全修复：使用 F() 表达式原子扣除，并检查更新结果
        from django.db.models import F
        updated = InventoryItem.objects.filter(
            pk=inventory_item.pk,
            quantity__gte=1,
        ).update(quantity=F('quantity') - 1)

        if not updated:
            raise ValueError("道具消耗失败，请重试")

        # 清理零库存记录（使用条件删除避免竞态条件）
        InventoryItem.objects.filter(
            pk=inventory_item.pk,
            quantity__lte=0,
        ).delete()

    # 更新庄园名称
    old_name = manor.name or manor.display_name
    manor.name = new_name
    manor.save(update_fields=['name'])

    # 发送系统消息
    from .messages import create_message
    create_message(
        manor=manor,
        kind=Message.Kind.SYSTEM,
        title="庄园更名成功",
        body=f"您的庄园已从「{old_name}」更名为「{new_name}」",
    )


def get_rename_card_count(manor: Manor) -> int:
    """
    获取玩家拥有的庄园命名卡数量。

    Args:
        manor: 庄园对象

    Returns:
        命名卡数量
    """
    from ..models import InventoryItem, ItemTemplate

    try:
        rename_card = ItemTemplate.objects.get(key='manor_rename_card')
    except ItemTemplate.DoesNotExist:
        return 0

    item = InventoryItem.objects.filter(
        manor=manor,
        template=rename_card,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).first()

    return item.quantity if item else 0
