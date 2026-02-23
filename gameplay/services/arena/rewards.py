from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

from common.constants.resources import ResourceType
from core.utils.yaml_loader import ensure_list, ensure_mapping, load_yaml_data

logger = logging.getLogger(__name__)

ARENA_REWARDS_PATH = Path(settings.BASE_DIR) / "data" / "arena_rewards.yaml"


@dataclass(frozen=True)
class ArenaRewardDefinition:
    key: str
    name: str
    cost_coins: int
    daily_limit: int | None
    resources: dict[str, int]
    items: dict[str, int]
    description: str = ""


def _to_positive_int(raw: Any, *, default: int = 0) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return max(0, int(default))
    return max(0, value)


def _normalize_reward_payload(payload: dict[str, Any], *, context: str) -> tuple[dict[str, int], dict[str, int]]:
    rewards = ensure_mapping(payload.get("rewards"), logger=logger, context=f"{context}.rewards")
    resources_raw = ensure_mapping(rewards.get("resources"), logger=logger, context=f"{context}.rewards.resources")
    items_raw = ensure_mapping(rewards.get("items"), logger=logger, context=f"{context}.rewards.items")

    resources: dict[str, int] = {}
    for key, amount in resources_raw.items():
        normalized_key = str(key).strip()
        if normalized_key not in ResourceType.values:
            logger.warning("arena reward contains unknown resource key: %s (%s)", normalized_key, context)
            continue
        normalized_amount = _to_positive_int(amount)
        if normalized_amount > 0:
            resources[normalized_key] = normalized_amount

    items: dict[str, int] = {}
    for key, amount in items_raw.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        normalized_amount = _to_positive_int(amount)
        if normalized_amount > 0:
            items[normalized_key] = normalized_amount

    return resources, items


@lru_cache(maxsize=1)
def load_arena_reward_catalog() -> dict[str, ArenaRewardDefinition]:
    raw = load_yaml_data(
        ARENA_REWARDS_PATH,
        logger=logger,
        context="arena rewards config",
        default={"rewards": []},
    )
    payload = ensure_mapping(raw, logger=logger, context="arena rewards root")
    rows = ensure_list(payload.get("rewards"), logger=logger, context="arena rewards entries")

    catalog: dict[str, ArenaRewardDefinition] = {}
    for idx, row in enumerate(rows):
        context = f"arena rewards[{idx}]"
        entry = ensure_mapping(row, logger=logger, context=context)
        key = str(entry.get("key") or "").strip()
        if not key:
            logger.warning("skip arena reward without key: %s", context)
            continue
        if key in catalog:
            logger.warning("duplicate arena reward key ignored: %s", key)
            continue

        cost_coins = _to_positive_int(entry.get("cost_coins"))
        if cost_coins <= 0:
            logger.warning("skip arena reward with invalid cost_coins: %s", key)
            continue

        resources, items = _normalize_reward_payload(entry, context=context)
        if not resources and not items:
            logger.warning("skip arena reward without payload: %s", key)
            continue

        daily_limit_value = _to_positive_int(entry.get("daily_limit"))
        daily_limit = daily_limit_value if daily_limit_value > 0 else None

        catalog[key] = ArenaRewardDefinition(
            key=key,
            name=str(entry.get("name") or key),
            cost_coins=cost_coins,
            daily_limit=daily_limit,
            resources=resources,
            items=items,
            description=str(entry.get("description") or ""),
        )

    return catalog


def get_arena_reward_definition(reward_key: str) -> ArenaRewardDefinition | None:
    key = str(reward_key or "").strip()
    if not key:
        return None
    return load_arena_reward_catalog().get(key)


def clear_arena_reward_cache() -> None:
    load_arena_reward_catalog.cache_clear()
