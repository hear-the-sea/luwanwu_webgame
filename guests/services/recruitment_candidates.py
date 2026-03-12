from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable

from ..models import GuestRarity, GuestTemplate, RecruitmentCandidate

if TYPE_CHECKING:
    from gameplay.models import Manor

    from ..models import RecruitmentPool, RecruitmentPoolEntry

ChooseTemplateFunc = Callable[..., GuestTemplate]
GenerateNameFunc = Callable[[random.Random], str]


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
    templates_by_rarity,
    hermit_templates,
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
