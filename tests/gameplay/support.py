from guests.models import RecruitmentPool
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate


def recruit_frontline_guests(manor, *, count: int = 3, start_seed: int = 0) -> None:
    pool = RecruitmentPool.objects.get(key="cunmu")
    for seed in range(start_seed, start_seed + count):
        candidates = recruit_guest(manor, pool, seed=seed)
        finalize_candidate(candidates[0])
