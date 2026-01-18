from __future__ import annotations

import random
from typing import Dict


def resolve_drop_rewards(drop_table: Dict[str, float | int | dict], rng: random.Random | None = None) -> Dict[str, int]:
    """
    Resolve a YAML-like drop table into concrete drops.

    Rules:
    - value >= 1: guaranteed amount
    - value < 1: probability to drop 1
    - value is dict: supports {"chance"/"probability", "count"/"quantity"/"amount"}
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

        # Guaranteed drop (value >= 1)
        if isinstance(value, (int, float)) and value >= 1:
            drops[key] = int(value)
        # Probabilistic drop (value < 1)
        elif isinstance(value, (int, float)):
            probability = float(value)
            if probability <= 0:
                continue
            if rng.random() <= probability:
                drops[key] = 1

    return drops

