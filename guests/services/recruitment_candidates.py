from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, TypedDict

from ..models import GuestRarity, GuestTemplate, RecruitmentCandidate

if TYPE_CHECKING:
    from gameplay.models import Manor

    from ..models import RecruitmentPool, RecruitmentPoolEntry

ChooseTemplateFunc = Callable[..., GuestTemplate]
GenerateNameFunc = Callable[[random.Random], str]


class CandidateGenerationContext(TypedDict):
    pool_entries: list[RecruitmentPoolEntry]
    rng: random.Random
    templates_by_rarity: dict[str, list[GuestTemplate]]
    hermit_templates: list[GuestTemplate]
    resolved_draw_count: int
    excluded_ids: set[int]


def resolve_candidate_draw_count(*, pool: RecruitmentPool, manor: Manor, total_draw_count: int | None) -> int:
    resolved_draw_count = total_draw_count
    if resolved_draw_count is None:
        resolved_draw_count = pool.draw_count + manor.tavern_recruitment_bonus
    return max(1, int(resolved_draw_count))


def build_candidate_display_name(
    template: GuestTemplate,
    rng: random.Random,
    *,
    generate_random_name: GenerateNameFunc,
) -> str:
    if template.rarity in (GuestRarity.BLACK, GuestRarity.GRAY) and not template.is_hermit:
        return generate_random_name(rng)
    return template.name


def should_reveal_candidate_rarity(template: GuestTemplate) -> bool:
    return template.rarity in (GuestRarity.RED, GuestRarity.GRAY)


def should_exclude_candidate_template(template: GuestTemplate, *, non_repeatable_rarities: frozenset[str]) -> bool:
    return template.rarity in non_repeatable_rarities or (template.rarity == GuestRarity.BLACK and template.is_hermit)


def build_candidate_batch(
    *,
    manor: Manor,
    pool: RecruitmentPool,
    pool_entries: list[RecruitmentPoolEntry],
    resolved_draw_count: int,
    excluded_ids: set[int],
    rng: random.Random,
    choose_template_from_entries: ChooseTemplateFunc,
    templates_by_rarity: dict[str, list[GuestTemplate]],
    hermit_templates: list[GuestTemplate],
    generate_random_name: GenerateNameFunc,
    non_repeatable_rarities: frozenset[str],
) -> list[RecruitmentCandidate]:
    candidates_to_create: list[RecruitmentCandidate] = []
    for _ in range(resolved_draw_count):
        template = choose_template_from_entries(
            pool_entries,
            rng=rng,
            excluded_ids=excluded_ids,
            templates_by_rarity=templates_by_rarity,
            hermit_templates=hermit_templates,
        )
        candidates_to_create.append(
            RecruitmentCandidate(
                manor=manor,
                pool=pool,
                template=template,
                display_name=build_candidate_display_name(
                    template,
                    rng,
                    generate_random_name=generate_random_name,
                ),
                rarity=template.rarity,
                archetype=template.archetype,
                rarity_revealed=should_reveal_candidate_rarity(template),
            )
        )
        if should_exclude_candidate_template(template, non_repeatable_rarities=non_repeatable_rarities):
            excluded_ids.add(template.id)
    return candidates_to_create


def load_candidate_generation_context(
    *,
    manor: Manor,
    pool: RecruitmentPool,
    seed: int | None,
    total_draw_count: int | None,
    get_recruitable_templates_by_rarity: Callable[[], dict[str, list[GuestTemplate]]],
    get_hermit_templates: Callable[[], list[GuestTemplate]],
    get_excluded_template_ids: Callable[[Manor], set[int]],
) -> CandidateGenerationContext:
    return {
        "pool_entries": list(pool.entries.select_related("template")),
        "rng": random.Random(seed),
        "templates_by_rarity": get_recruitable_templates_by_rarity(),
        "hermit_templates": get_hermit_templates(),
        "resolved_draw_count": resolve_candidate_draw_count(pool=pool, manor=manor, total_draw_count=total_draw_count),
        "excluded_ids": get_excluded_template_ids(manor),
    }


def persist_candidate_batch(
    *,
    recruitment_candidate_model: type[RecruitmentCandidate],
    manor: Manor,
    candidates_to_create: list[RecruitmentCandidate],
    invalidate_cache: Callable[[int | None], None],
) -> list[RecruitmentCandidate]:
    candidates = recruitment_candidate_model.objects.bulk_create(candidates_to_create)
    if candidates and any(getattr(candidate, "pk", None) is None for candidate in candidates):
        created_ids = list(
            recruitment_candidate_model.objects.filter(manor=manor)
            .order_by("-id")
            .values_list("id", flat=True)[: len(candidates_to_create)]
        )
        created_ids.reverse()
        candidates = list(recruitment_candidate_model.objects.filter(id__in=created_ids).order_by("id"))
    invalidate_cache(getattr(manor, "id", None))
    return candidates
