from __future__ import annotations

from gameplay.services.utils.cache import invalidate_recruitment_hall_cache as _invalidate_recruitment_hall_cache

from ..models import GuestRarity, RecruitmentPool

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
    _invalidate_recruitment_hall_cache(int(manor_id))


__all__ = [
    "CORE_POOL_TIERS",
    "NON_REPEATABLE_RARITIES",
    "invalidate_recruitment_hall_cache",
]
