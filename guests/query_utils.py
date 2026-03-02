from __future__ import annotations

from django.db.models import Case, IntegerField, Value, When

# 稀有度业务顺序（从低到高），需与 guests.models.GuestRarity 保持一致。
_GUEST_RARITY_ORDER = (
    "black",
    "gray",
    "green",
    "red",
    "blue",
    "purple",
    "orange",
)


def guest_template_rarity_rank_case(field_name: str = "template__rarity") -> Case:
    """
    返回可用于 annotate 的稀有度排序表达式（值越大表示稀有度越高）。
    """
    whens = [When(**{field_name: rarity}, then=Value(rank)) for rank, rarity in enumerate(_GUEST_RARITY_ORDER)]
    return Case(
        *whens,
        default=Value(-1),
        output_field=IntegerField(),
    )
