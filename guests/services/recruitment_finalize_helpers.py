from __future__ import annotations

import random
from collections.abc import Callable
from typing import TYPE_CHECKING

from core.exceptions import GuestCapacityFullError, RetainerCapacityFullError

if TYPE_CHECKING:
    from gameplay.models import Manor

    from ..models import Guest, GuestTemplate, RecruitmentCandidate, RecruitmentRecord

if TYPE_CHECKING:
    CreateGuestFunc = Callable[..., Guest]
    ShouldUseCustomNameFunc = Callable[[RecruitmentCandidate, GuestTemplate], bool]
else:
    CreateGuestFunc = Callable[..., object]
    ShouldUseCustomNameFunc = Callable[[object, object], bool]


def remaining_guest_capacity(manor: Manor) -> int:
    return max(0, int(getattr(manor, "guest_capacity", 0) or 0) - int(manor.guests.count()))


def ensure_guest_capacity_available(manor: Manor) -> int:
    remaining = remaining_guest_capacity(manor)
    if remaining <= 0:
        raise GuestCapacityFullError()
    return remaining


def split_candidates_by_capacity(
    candidates: list[RecruitmentCandidate], *, available_slots: int
) -> tuple[list[RecruitmentCandidate], list[RecruitmentCandidate]]:
    normalized_slots = max(0, int(available_slots))
    return candidates[:normalized_slots], candidates[normalized_slots:]


def build_guest_from_candidate(
    *,
    candidate: RecruitmentCandidate,
    manor: Manor,
    rng: random.Random,
    create_guest_func: CreateGuestFunc,
    should_use_candidate_custom_name: ShouldUseCustomNameFunc,
) -> Guest:
    template = candidate.template
    use_custom_name = should_use_candidate_custom_name(candidate, template)
    return create_guest_func(
        manor=manor,
        template=template,
        rarity=candidate.rarity,
        archetype=candidate.archetype,
        custom_name=candidate.display_name if use_custom_name else "",
        rng=rng,
    )


def create_recruitment_record(
    *,
    recruitment_record_model: type[RecruitmentRecord],
    manor: Manor,
    candidate: RecruitmentCandidate,
    guest: Guest,
) -> RecruitmentRecord:
    return recruitment_record_model.objects.create(
        manor=manor,
        pool=candidate.pool,
        guest=guest,
        rarity=candidate.rarity,
    )


def save_guest_objects(guest_objects: list[Guest]) -> list[Guest]:
    created_guests: list[Guest] = []
    for guest_obj in guest_objects:
        guest_obj.save()
        created_guests.append(guest_obj)
    return created_guests


def delete_processed_candidates(
    *, recruitment_candidate_model: type[RecruitmentCandidate], candidate_ids_to_delete: list[int]
) -> None:
    if not candidate_ids_to_delete:
        return
    recruitment_candidate_model.objects.filter(id__in=candidate_ids_to_delete).delete()


def validate_retainer_candidate_identity(candidate: RecruitmentCandidate) -> tuple[int, int]:
    candidate_id = getattr(candidate, "pk", None)
    manor_id = getattr(candidate, "manor_id", None)
    if not candidate_id or not manor_id:
        raise ValueError("候选门客不存在或已处理")
    return int(candidate_id), int(manor_id)


def load_locked_retainer_candidate(
    *, recruitment_candidate_model: type[RecruitmentCandidate], candidate_id: int, manor_id: int
) -> RecruitmentCandidate | None:
    return recruitment_candidate_model.objects.select_for_update().filter(pk=candidate_id, manor_id=manor_id).first()


def ensure_retainer_capacity_available(manor: Manor) -> None:
    if manor.retainer_count >= manor.retainer_capacity:
        raise RetainerCapacityFullError()


def increment_retainer_count_locked(manor: Manor) -> None:
    manor.retainer_count += 1
    manor.save(update_fields=["retainer_count"])
