"""
掉落奖励生成工具模块

处理任务掉落奖励的随机生成和发放。
"""
from __future__ import annotations

import random
from typing import Dict


def resolve_drop_rewards(drop_table: Dict[str, float | int | dict], rng: random.Random | None = None) -> Dict[str, int]:
    """
    根据掉落表生成实际掉落奖励。

    掉落表规则：
    - 值 >= 1：确定获得该数量（如 {"silver": 100} 必得100银两）
    - 值 < 1：按概率掉落1个（如 {"rare_item": 0.1} 有10%概率获得）
    - 值为字典：支持概率与数量组合（如 {"rare_item": {"chance": 0.2, "count": 5}}）

    Args:
        drop_table: 掉落表 {"item_key": amount_or_probability_or_config, ...}
        rng: 随机数生成器（可选）

    Returns:
        实际掉落字典 {"item_key": count, ...}

    Examples:
        >>> rng = random.Random(42)
        >>> resolve_drop_rewards({"silver": 100, "rare_gem": 0.5}, rng)
        {"silver": 100, "rare_gem": 1}  # 或 {"silver": 100} 取决于概率
    """
    rng = rng or random.Random()
    drops: Dict[str, int] = {}

    for key, value in (drop_table or {}).items():
        if value is None:
            continue

        if isinstance(value, dict):
            chance = value.get("chance", value.get("probability"))
            count = value.get("count", value.get("quantity", value.get("amount")))

            try:
                chance = float(chance) if chance is not None else None
            except (TypeError, ValueError):
                chance = None

            try:
                count = int(count) if count is not None else None
            except (TypeError, ValueError):
                count = None

            if count is None:
                count = 1

            if chance is None:
                if count > 0:
                    drops[key] = drops.get(key, 0) + count
                continue

            if chance <= 0:
                continue

            if chance >= 1 or rng.random() <= chance:
                drops[key] = drops.get(key, 0) + count
            continue

        # 确定掉落（值 >= 1）
        if isinstance(value, (int, float)) and value >= 1:
            drops[key] = int(value)
        # 概率掉落（值 < 1）
        elif isinstance(value, (int, float)):
            probability = float(value)
            if probability <= 0:
                continue
            if rng.random() <= probability:
                drops[key] = 1

    return drops
