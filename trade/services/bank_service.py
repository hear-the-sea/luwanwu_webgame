"""
钱庄服务

动态汇率机制：
  实时汇率 = 基准价 × 总量系数 × 累进系数

  - 总量系数：基于活跃玩家的金条总量，金条越多价格越高（通胀控制）
  - 累进系数：基于当日个人已兑换数量，越买越贵（软限制）
"""

import logging
import math
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from gameplay.models import InventoryItem, ItemTemplate, Manor, ResourceEvent
from gameplay.services.resources import spend_resources_locked
from trade.models import GoldBarExchangeLog

logger = logging.getLogger(__name__)


# 金条基础配置
GOLD_BAR_ITEM_KEY = "gold_bar"
GOLD_BAR_BASE_PRICE = 1_000_000  # 基准价100万银两
GOLD_BAR_FEE_RATE = Decimal("0.10")  # 10%手续费

# 动态汇率配置
GOLD_BAR_TARGET_SUPPLY = 1000  # 基准活跃金条量
GOLD_BAR_MIN_PRICE = 800_000  # 最低价80万
GOLD_BAR_MAX_PRICE = 1_600_000  # 最高价160万
GOLD_BAR_SUPPLY_FACTOR = 0.12  # 总量系数调节因子
GOLD_BAR_PROGRESSIVE_FACTOR = 0.05  # 累进系数：每根+5%
ACTIVE_DAYS_THRESHOLD = 14  # 活跃判定天数

# 缓存配置
SUPPLY_CACHE_KEY = "gold_bar:effective_supply"
SUPPLY_CACHE_TTL = 300  # 缓存5分钟
SUPPLY_STALE_CACHE_KEY = "gold_bar:effective_supply:stale"
SUPPLY_STALE_CACHE_TTL = 3600  # 过期缓存保留1小时，用于降级


def get_today_exchange_count(manor: Manor) -> int:
    """获取今日已兑换金条数量"""
    # 安全修复：使用 timezone.now().date() 保持时区一致性
    today = timezone.now().date()
    count = GoldBarExchangeLog.objects.filter(
        manor=manor, exchange_date=today
    ).aggregate(total=Sum("quantity"))["total"]
    return count or 0


# ============ 动态汇率计算 ============


def get_effective_gold_supply() -> int:
    """
    获取有效金条供应量（仅统计活跃玩家）

    只统计最近 ACTIVE_DAYS_THRESHOLD 天内有登录的玩家持有的金条，
    排除弃游玩家的"死金条"对汇率的影响。

    缓存策略（三级降级）：
    1. 主缓存有效 → 直接返回
    2. 主缓存失效 + 获取锁成功 → 查询数据库并更新缓存
    3. 主缓存失效 + 获取锁失败 → 使用过期缓存（stale cache）
    4. 过期缓存也没有 → 返回默认值

    Returns:
        int: 活跃玩家持有的金条总量
    """
    cached = cache.get(SUPPLY_CACHE_KEY)
    if cached is not None:
        return cached

    # 缓存击穿保护：使用分布式锁防止并发查询
    lock_key = f"{SUPPLY_CACHE_KEY}:lock"
    lock_acquired = cache.add(lock_key, "1", timeout=10)  # 10秒锁超时

    if not lock_acquired:
        # 未获取到锁，等待短暂时间后重试获取缓存
        import time
        time.sleep(0.1)
        cached = cache.get(SUPPLY_CACHE_KEY)
        if cached is not None:
            return cached
        # 降级策略：使用过期缓存（stale cache），避免使用硬编码默认值
        stale = cache.get(SUPPLY_STALE_CACHE_KEY)
        if stale is not None:
            logger.info("Gold supply cache miss, using stale cache value: %d", stale)
            return stale
        # 过期缓存也没有，返回默认值
        logger.warning("Gold supply cache miss and no stale cache, using default")
        return GOLD_BAR_TARGET_SUPPLY

    try:
        cutoff = timezone.now() - timedelta(days=ACTIVE_DAYS_THRESHOLD)

        result = InventoryItem.objects.filter(
            template__key=GOLD_BAR_ITEM_KEY,
            manor__user__last_login__gte=cutoff,
        ).aggregate(total=Sum("quantity"))

        total = result["total"] or 0
        # 同时更新主缓存和过期缓存（过期缓存TTL更长，用于降级）
        cache.set(SUPPLY_CACHE_KEY, total, SUPPLY_CACHE_TTL)
        cache.set(SUPPLY_STALE_CACHE_KEY, total, SUPPLY_STALE_CACHE_TTL)
        return total
    except Exception as e:
        logger.warning(f"Failed to query gold supply: {e}")
        # 降级策略：优先使用过期缓存
        stale = cache.get(SUPPLY_STALE_CACHE_KEY)
        if stale is not None:
            return stale
        return GOLD_BAR_TARGET_SUPPLY
    finally:
        cache.delete(lock_key)


def calculate_supply_factor() -> float:
    """
    计算总量系数

    基于活跃玩家的金条总量，使用对数函数平滑调节：
    - 金条总量 < 基准量：系数 < 1（价格降低，鼓励兑换）
    - 金条总量 > 基准量：系数 > 1（价格上涨，抑制兑换）

    Returns:
        float: 总量系数，范围 0.85 ~ 1.40
    """
    total_supply = get_effective_gold_supply()

    if total_supply <= 0:
        return 0.85  # 无金条时给最低价

    ratio = total_supply / GOLD_BAR_TARGET_SUPPLY
    factor = 1 + GOLD_BAR_SUPPLY_FACTOR * math.log2(ratio)

    return max(0.85, min(1.40, factor))


def calculate_progressive_factor(today_count: int) -> float:
    """
    计算累进系数

    基于当日个人已兑换数量，每兑换一根价格上涨5%：
    - 第1根：1.05
    - 第5根：1.25
    - 第10根：1.50
    - 第12根及以上：1.60（封顶）

    Args:
        today_count: 当日已兑换数量

    Returns:
        float: 累进系数，范围 1.0 ~ 1.60
    """
    factor = 1 + GOLD_BAR_PROGRESSIVE_FACTOR * today_count
    return min(factor, 1.60)


def calculate_dynamic_rate(manor: Manor) -> int:
    """
    计算当前动态汇率

    公式：实时汇率 = 基准价 × 总量系数 × 累进系数

    Args:
        manor: 庄园对象

    Returns:
        int: 当前汇率（银两/金条）
    """
    supply_factor = calculate_supply_factor()
    today_count = get_today_exchange_count(manor)
    progressive_factor = calculate_progressive_factor(today_count)

    rate = int(GOLD_BAR_BASE_PRICE * supply_factor * progressive_factor)
    return max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, rate))


def calculate_next_rate(manor: Manor) -> int:
    """
    计算下一根金条的汇率（用于显示）

    Args:
        manor: 庄园对象

    Returns:
        int: 下一根金条的汇率
    """
    supply_factor = calculate_supply_factor()
    today_count = get_today_exchange_count(manor)
    # 下一根的累进系数应基于“今日已兑换数量 + 1”
    progressive_factor = calculate_progressive_factor(today_count + 1)

    rate = int(GOLD_BAR_BASE_PRICE * supply_factor * progressive_factor)
    return max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, rate))


def calculate_gold_bar_cost(manor: Manor, quantity: int) -> dict:
    """
    计算兑换金条所需银两（含手续费）

    由于累进系数的存在，每根金条的价格都可能不同，
    需要逐根计算总价。

    Args:
        manor: 庄园对象
        quantity: 兑换数量

    Returns:
        dict: 包含各项费用明细
    """
    supply_factor = calculate_supply_factor()
    today_count = get_today_exchange_count(manor)

    base_cost = 0
    rate_details = []

    for i in range(quantity):
        progressive_factor = calculate_progressive_factor(today_count + i)
        rate = int(GOLD_BAR_BASE_PRICE * supply_factor * progressive_factor)
        rate = max(GOLD_BAR_MIN_PRICE, min(GOLD_BAR_MAX_PRICE, rate))
        base_cost += rate
        rate_details.append(rate)

    fee = int(base_cost * GOLD_BAR_FEE_RATE)
    total_cost = base_cost + fee

    return {
        "base_cost": base_cost,
        "fee": fee,
        "total_cost": total_cost,
        "rate_details": rate_details,
        "avg_rate": base_cost // quantity if quantity > 0 else 0,
    }


def exchange_gold_bar(manor: Manor, quantity: int) -> dict:
    """
    兑换金条（动态汇率版本）

    汇率会根据全服活跃金条总量和个人当日已兑换数量动态调整。
    移除了每日硬性限额，但累进系数会使大量兑换变得昂贵。

    Args:
        manor: 庄园对象
        quantity: 兑换数量

    Returns:
        dict: 兑换结果信息

    Raises:
        ValueError: 参数错误、银两不足等
    """
    if quantity <= 0:
        raise ValueError("兑换数量必须大于0")

    # 计算所需银两（动态汇率，逐根计算）
    cost_info = calculate_gold_bar_cost(manor, quantity)
    total_cost = cost_info["total_cost"]

    # 检查金条物品模板是否存在
    try:
        gold_bar_template = ItemTemplate.objects.get(key=GOLD_BAR_ITEM_KEY)
    except ItemTemplate.DoesNotExist:
        raise ValueError("金条物品不存在，请联系管理员")

    # 执行兑换（并发安全版本）
    with transaction.atomic():
        manor_locked = Manor.objects.select_for_update().get(pk=manor.pk)

        # 锁内检查银两是否足够，避免并发下展示错误信息或透支
        if manor_locked.silver < total_cost:
            raise ValueError(
                f"银两不足，需要 {total_cost:,} 银两"
                f"（基础 {cost_info['base_cost']:,} + 手续费 {cost_info['fee']:,}）"
            )

        # 步骤1：消耗银两
        spend_resources_locked(
            manor_locked,
            {"silver": total_cost},
            note=f"兑换金条 x{quantity}",
            reason=ResourceEvent.Reason.BANK_EXCHANGE,
        )

        # 步骤2：锁定并增加金条库存
        # 锁定现有记录避免并发时数量增加被覆盖
        inventory_item = (
            InventoryItem.objects.select_for_update()
            .filter(
                manor=manor_locked,
                template=gold_bar_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
            .first()
        )

        if inventory_item:
            # 已有金条，使用F()表达式增加数量
            InventoryItem.objects.filter(pk=inventory_item.pk).update(
                quantity=F("quantity") + quantity
            )
        else:
            # 首次获得金条，创建新记录
            InventoryItem.objects.create(
                manor=manor_locked,
                template=gold_bar_template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity=quantity,
            )

        # 步骤3：记录兑换日志
        GoldBarExchangeLog.objects.create(
            manor=manor_locked, quantity=quantity, silver_cost=total_cost
        )

    # 清除供应量缓存，让下次查询获取最新数据
    cache.delete(SUPPLY_CACHE_KEY)

    return {
        "quantity": quantity,
        "total_cost": total_cost,
        "base_cost": cost_info["base_cost"],
        "fee": cost_info["fee"],
        "avg_rate": cost_info["avg_rate"],
        "rate_details": cost_info["rate_details"],
        "next_rate": calculate_next_rate(manor),
    }


def get_bank_info(manor: Manor) -> dict:
    """
    获取钱庄信息（动态汇率版本）

    Returns:
        dict: 包含动态汇率、手续费率、今日兑换情况等信息
    """
    today_count = get_today_exchange_count(manor)
    current_rate = calculate_dynamic_rate(manor)
    next_rate = calculate_next_rate(manor)
    supply_factor = calculate_supply_factor()
    progressive_factor = calculate_progressive_factor(today_count)

    # 计算单根金条的总费用（含手续费）
    cost_info = calculate_gold_bar_cost(manor, 1)

    return {
        # 基础配置
        "gold_bar_base_price": GOLD_BAR_BASE_PRICE,
        "gold_bar_fee_rate": float(GOLD_BAR_FEE_RATE) * 100,  # 转换为百分比
        "gold_bar_min_price": GOLD_BAR_MIN_PRICE,
        "gold_bar_max_price": GOLD_BAR_MAX_PRICE,
        # 动态汇率信息
        "current_rate": current_rate,
        "next_rate": next_rate,
        "total_cost_per_bar": cost_info["total_cost"],
        "supply_factor": round(supply_factor, 3),
        "progressive_factor": round(progressive_factor, 3),
        "effective_supply": get_effective_gold_supply(),
        # 个人兑换情况
        "today_count": today_count,
        "manor_silver": manor.silver,
    }
