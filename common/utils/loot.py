from __future__ import annotations

import logging
import random
import secrets
from typing import Dict

logger = logging.getLogger(__name__)


def _create_default_rng() -> random.Random:
    return random.Random(secrets.randbits(128))


def _add_drop(drops: Dict[str, int], key: str, count: int) -> None:
    if count <= 0:
        return
    drops[key] = drops.get(key, 0) + int(count)


def _parse_numeric_drop_value(value: float | int) -> tuple[float | None, int]:
    if value >= 1:
        return None, int(value)
    return float(value), 1


def _parse_dict_drop_value(value: dict) -> tuple[float | None, int]:
    chance_raw = value.get("chance", value.get("probability"))
    count_raw = value.get("count", value.get("quantity", value.get("amount")))

    try:
        chance = float(chance_raw) if chance_raw is not None else None
    except (TypeError, ValueError):
        chance = None

    try:
        count = int(count_raw) if count_raw is not None else None
    except (TypeError, ValueError):
        count = None

    if count is None:
        count = 1
    return chance, count


def _should_drop(chance: float | None, rng: random.Random) -> bool:
    if chance is None:
        return True
    if chance <= 0:
        return False
    if chance >= 1:
        return True
    return rng.random() < chance


def _resolve_drop_entry(value: float | int | dict) -> tuple[float | None, int] | None:
    if isinstance(value, dict):
        chance, count = _parse_dict_drop_value(value)
        return chance, count

    if isinstance(value, (int, float)):
        chance, count = _parse_numeric_drop_value(value)
        if chance is not None and chance <= 0:
            return None
        return chance, count

    return None


def resolve_drop_rewards(drop_table: Dict[str, float | int | dict], rng: random.Random | None = None) -> Dict[str, int]:
    """
    Resolve a YAML-like drop table into concrete drops.

    Rules:
    - value >= 1: guaranteed amount
    - value < 1: probability to drop 1
    - value is dict: supports {"chance"/"probability", "count"/"quantity"/"amount"}

    Args:
        drop_table: 掉落配置表
        rng: 随机数生成器（如果不传入，将使用加密安全的种子创建）

    Returns:
        Dict[str, int]: 实际掉落物品及数量
    """
    # 使用加密安全的随机种子，防止掉落结果被预测
    if rng is None:
        rng = _create_default_rng()
    drops: Dict[str, int] = {}

    for key, value in (drop_table or {}).items():
        if value is None:
            continue

        resolved = _resolve_drop_entry(value)
        if resolved is None:
            continue
        chance, count = resolved
        if _should_drop(chance, rng):
            _add_drop(drops, key, count)

    return drops
