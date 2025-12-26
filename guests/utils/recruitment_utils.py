"""
招募系统工具模块

提供门客招募相关的计算和工具函数，包括稀有度抽取、权重选择等。
"""
from __future__ import annotations

import random
from typing import List

from ..models import GuestRarity, RecruitmentPoolEntry


# 稀有度排序（从低到高）
RARITY_ORDER = [
    GuestRarity.BLACK,
    GuestRarity.GRAY,
    GuestRarity.GREEN,
    GuestRarity.RED,
    GuestRarity.BLUE,
    GuestRarity.PURPLE,
    GuestRarity.ORANGE,
]

# 隐士类型标识（虽显示为黑色，但有独立抽取概率）
HERMIT_RARITY = "hermit"

# 稀有度权重配置（累计概率抽卡）
RARITY_WEIGHTS = [
    (GuestRarity.ORANGE, 200),   # 0.02%
    (HERMIT_RARITY, 300),        # 0.03% 隐士（隐藏在民间的高手）
    (GuestRarity.PURPLE, 500),   # 0.05%
    (GuestRarity.RED, 3000),     # 0.3%
    (GuestRarity.BLUE, 1000),    # 0.1%
    (GuestRarity.GREEN, 10000),  # 1%
    (GuestRarity.GRAY, 50000),   # 5%
]

TOTAL_WEIGHT = 1_000_000
BLACK_WEIGHT = TOTAL_WEIGHT - sum(weight for _, weight in RARITY_WEIGHTS)
RARITY_DISTRIBUTION = RARITY_WEIGHTS + [(GuestRarity.BLACK, max(BLACK_WEIGHT, 0))]


def choose_rarity(rng: random.Random) -> str:
    """
    根据权重随机选择一个稀有度。
    
    使用累计权重方式实现概率抽取，确保稀有度分布符合预设比例。
    
    Args:
        rng: 随机数生成器
        
    Returns:
        稀有度字符串（BLACK/GRAY/GREEN等）
        
    Examples:
        >>> import random
        >>> rng = random.Random(42)
        >>> rarity = choose_rarity(rng)
        >>> rarity in ['black', 'gray', 'green', 'blue', 'red', 'purple', 'orange']
        True
    """
    roll = rng.randint(1, TOTAL_WEIGHT)
    cumulative = 0
    for rarity, weight in RARITY_DISTRIBUTION:
        cumulative += weight
        if roll <= cumulative:
            return rarity
    return GuestRarity.BLACK


def entry_rarity(entry: RecruitmentPoolEntry) -> str | None:
    """
    获取招募池条目的稀有度。
    
    如果条目指定了具体模板，返回模板的稀有度；
    否则返回条目自身的稀有度配置。
    
    Args:
        entry: 招募池条目
        
    Returns:
        稀有度字符串，如果无法确定则返回 None
    """
    if entry.template_id:
        return entry.template.rarity
    return entry.rarity


def filter_entries(entries: List[RecruitmentPoolEntry], rarity: str) -> List[RecruitmentPoolEntry]:
    """
    筛选出指定稀有度的招募池条目。
    
    Args:
        entries: 招募池条目列表
        rarity: 目标稀有度
        
    Returns:
        符合稀有度的条目列表
    """
    return [entry for entry in entries if entry_rarity(entry) == rarity]


def weighted_choice(entries: List[RecruitmentPoolEntry], rng: random.Random) -> RecruitmentPoolEntry:
    """
    根据权重从条目列表中随机选择一个。
    
    每个条目可配置权重（weight字段），权重越高被选中概率越大。
    如果未配置权重，默认权重为1。
    
    Args:
        entries: 招募池条目列表
        rng: 随机数生成器
        
    Returns:
        被选中的条目
        
    Raises:
        IndexError: 如果条目列表为空
    """
    total = sum(entry.weight or 1 for entry in entries) or len(entries)
    pick = rng.uniform(0, total)
    upto = 0
    for entry in entries:
        upto += entry.weight or 1
        if upto >= pick:
            return entry
    return entries[-1]
