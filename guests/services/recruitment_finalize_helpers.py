from __future__ import annotations

import random
from collections.abc import Callable

from core.exceptions import GuestCapacityFullError, RetainerCapacityFullError

CreateGuestFunc = Callable[..., object]
ShouldUseCustomNameFunc = Callable[..., bool]


def remaining_guest_capacity(manor) -> int:
    return max(0, int(getattr(manor, "guest_capacity", 0) or 0) - int(manor.guests.count()))


def ensure_guest_capacity_available(manor) -> int:
    remaining = remaining_guest_capacity(manor)
    if remaining <= 0:
        raise GuestCapacityFullError()
    return remaining


def split_candidates_by_capacity(candidates: list, *, available_slots: int) -> tuple[list, list]:
    normalized_slots = max(0, int(available_slots))
    return candidates[:normalized_slots], candidates[normalized_slots:]


def build_guest_from_candidate(
    *,
    candidate,
    manor,
    rng: random.Random,
    create_guest_func: CreateGuestFunc,
    should_use_candidate_custom_name: ShouldUseCustomNameFunc,
):
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


def create_recruitment_record(*, recruitment_record_model, manor, candidate, guest):
    return recruitment_record_model.objects.create(
        manor=manor,
        pool=candidate.pool,
        guest=guest,
        rarity=candidate.rarity,
    )


def save_guest_objects(guest_objects: list) -> list:
    created_guests = []
    for guest_obj in guest_objects:
        guest_obj.save()
        created_guests.append(guest_obj)
    return created_guests


def delete_processed_candidates(*, recruitment_candidate_model, candidate_ids_to_delete: list[int]) -> None:
    if not candidate_ids_to_delete:
        return
    recruitment_candidate_model.objects.filter(id__in=candidate_ids_to_delete).delete()


def validate_retainer_candidate_identity(candidate) -> tuple[int, int]:
    candidate_id = getattr(candidate, "pk", None)
    manor_id = getattr(candidate, "manor_id", None)
    if not candidate_id or not manor_id:
        raise ValueError("候选门客不存在或已处理")
    return int(candidate_id), int(manor_id)


def load_locked_retainer_candidate(*, recruitment_candidate_model, candidate_id: int, manor_id: int):
    return recruitment_candidate_model.objects.select_for_update().filter(pk=candidate_id, manor_id=manor_id).first()


def ensure_retainer_capacity_available(manor) -> None:
    if manor.retainer_count >= manor.retainer_capacity:
        raise RetainerCapacityFullError()


def increment_retainer_count_locked(manor) -> None:
    manor.retainer_count += 1
    manor.save(update_fields=["retainer_count"])
