"""
招募系统工具模块

提供门客招募相关的计算和工具函数，包括稀有度抽取、权重选择等。
"""

from __future__ import annotations

import logging
import random
from functools import lru_cache
from pathlib import Path
from typing import List

from django.conf import settings

from common.utils.random_utils import cumulative_choice, weighted_random_choice
from core.utils.yaml_loader import ensure_mapping, load_yaml_data

from ..models import GuestRarity, RecruitmentPoolEntry

logger = logging.getLogger(__name__)

# 稀有度排序（从低到高），由 GuestRarity 定义顺序派生。
RARITY_ORDER = [rarity for rarity, _label in GuestRarity.choices]

# 隐士类型标识（虽显示为黑色，但有独立抽取概率）
HERMIT_RARITY = "hermit"

RECRUITMENT_RARITY_WEIGHTS_PATH = Path(settings.BASE_DIR) / "data" / "recruitment_rarity_weights.yaml"

_DEFAULT_TOTAL_WEIGHT = 1_000_000
_DEFAULT_WEIGHT_MAP = {
    GuestRarity.ORANGE: 4000,
    HERMIT_RARITY: 6000,
    GuestRarity.PURPLE: 10000,
    GuestRarity.RED: 0,
    GuestRarity.BLUE: 20000,
    GuestRarity.GREEN: 200000,
    GuestRarity.GRAY: 50000,
}
_RARITY_WEIGHT_ORDER = (
    GuestRarity.ORANGE,
    HERMIT_RARITY,
    GuestRarity.PURPLE,
    GuestRarity.RED,
    GuestRarity.BLUE,
    GuestRarity.GREEN,
    GuestRarity.GRAY,
)


def _to_non_negative_int(raw_value, *, default: int = 0) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return max(0, int(default))
    return max(0, value)


@lru_cache(maxsize=1)
def _load_rarity_distribution() -> tuple[int, tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]:
    raw = load_yaml_data(
        RECRUITMENT_RARITY_WEIGHTS_PATH,
        logger=logger,
        context="recruitment rarity weights config",
        default={},
    )
    payload = ensure_mapping(raw, logger=logger, context="recruitment rarity weights root")

    configured_total = _to_non_negative_int(payload.get("total_weight"), default=_DEFAULT_TOTAL_WEIGHT)
    if configured_total <= 0:
        configured_total = _DEFAULT_TOTAL_WEIGHT

    weights_payload = ensure_mapping(
        payload.get("weights"),
        logger=logger,
        context="recruitment rarity weights root.weights",
    )
    weight_map: dict[str, int] = {}
    for rarity in _RARITY_WEIGHT_ORDER:
        weight_map[rarity] = _to_non_negative_int(weights_payload.get(rarity), default=_DEFAULT_WEIGHT_MAP[rarity])

    rarity_weights = tuple((rarity, weight_map[rarity]) for rarity in _RARITY_WEIGHT_ORDER)
    total_non_black_weight = sum(weight for _, weight in rarity_weights)
    total_weight = max(configured_total, total_non_black_weight)
    black_weight = total_weight - total_non_black_weight

    rarity_distribution = rarity_weights + ((GuestRarity.BLACK, black_weight),)
    return total_weight, rarity_weights, rarity_distribution


def clear_recruitment_rarity_cache() -> None:
    _load_rarity_distribution.cache_clear()


def get_recruitment_rarity_distribution() -> tuple[int, list[tuple[str, int]], list[tuple[str, int]]]:
    total_weight, rarity_weights, rarity_distribution = _load_rarity_distribution()
    return total_weight, list(rarity_weights), list(rarity_distribution)


TOTAL_WEIGHT, _RARITY_WEIGHTS_TUPLE, _RARITY_DISTRIBUTION_TUPLE = _load_rarity_distribution()
RARITY_WEIGHTS = list(_RARITY_WEIGHTS_TUPLE)
BLACK_WEIGHT = _RARITY_DISTRIBUTION_TUPLE[-1][1]
RARITY_DISTRIBUTION = list(_RARITY_DISTRIBUTION_TUPLE)


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
    # 使用统一的累计权重选择函数
    total_weight, _rarity_weights, rarity_distribution = _load_rarity_distribution()
    return cumulative_choice(
        list(rarity_distribution),
        total_weight,
        rng,
        default=GuestRarity.BLACK,
    )


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
        # When a template_id exists, template should be populated, but keep a
        # defensive guard for stubs/missing relations.
        if entry.template is None:
            return None
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
    # 使用统一的加权随机选择函数
    weights = [entry.weight or 1 for entry in entries]
    return weighted_random_choice(entries, weights, rng)
