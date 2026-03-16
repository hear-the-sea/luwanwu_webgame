from __future__ import annotations

import logging

from ..models import GuestRarity, RecruitmentPool

logger = logging.getLogger(__name__)

NON_REPEATABLE_RARITIES = frozenset(
    {
        GuestRarity.GREEN,
        GuestRarity.BLUE,
        GuestRarity.RED,
        GuestRarity.PURPLE,
        GuestRarity.ORANGE,
    }
)

CORE_POOL_TIERS = (
    RecruitmentPool.Tier.CUNMU,
    RecruitmentPool.Tier.XIANGSHI,
    RecruitmentPool.Tier.HUISHI,
    RecruitmentPool.Tier.DIANSHI,
)


def invalidate_recruitment_hall_cache(manor_id: int | None) -> None:
    if not manor_id:
        return
    try:
        from gameplay.services.utils.cache import invalidate_recruitment_hall_cache

        invalidate_recruitment_hall_cache(int(manor_id))
    except Exception:
        logger.debug("Failed to invalidate recruitment hall cache for manor_id=%s", manor_id, exc_info=True)


__all__ = [
    "CORE_POOL_TIERS",
    "NON_REPEATABLE_RARITIES",
    "invalidate_recruitment_hall_cache",
]
