from __future__ import annotations

from guests.models import RecruitmentPool
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate


def recruit_frontline(manor, draws: int = 3) -> None:
    pool = RecruitmentPool.objects.get(key="cunmu")
    for seed in range(draws):
        candidates = recruit_guest(manor, pool, seed=seed + 1)
        finalize_candidate(candidates[0])


def build_snapshot_payload(**overrides):
    payload = {
        "guest_id": 1,
        "manor_id": 1,
        "display_name": "坏快照",
        "rarity": "green",
        "status": "idle",
        "template_key": "snapshot_tpl",
        "level": 1,
        "force": 1,
        "intellect": 1,
        "defense_stat": 1,
        "agility": 1,
        "luck": 1,
        "attack": 1,
        "defense": 1,
        "max_hp": 1,
        "current_hp": 1,
        "troop_capacity": 0,
        "skill_keys": [],
    }
    payload.update(overrides)
    return payload
