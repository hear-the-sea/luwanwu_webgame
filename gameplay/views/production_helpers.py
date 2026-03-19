from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence, Set
from typing import Any


def normalize_forge_category(
    raw_category: str | None,
    *,
    active_categories: Mapping[str, str],
    weapon_categories: Set[str],
) -> str:
    current_category = str(raw_category or "all")
    if current_category in weapon_categories:
        current_category = "weapon"

    valid_categories = {"all", *active_categories.keys()}
    if current_category not in valid_categories:
        return "all"
    return current_category


def sort_equipment_options(equipment_options: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        equipment_options,
        key=lambda item: (
            item.get("is_unlocked", False) and item.get("can_afford", False),
            item.get("required_forging", 0),
        ),
        reverse=True,
    )


def get_filtered_equipment_options(
    *,
    manor: object,
    current_category: str,
    weapon_categories: Set[str],
    get_equipment_options: Callable[..., list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if current_category == "all":
        equipment_list = get_equipment_options(manor)
    elif current_category == "weapon":
        equipment_list = [
            option for option in get_equipment_options(manor) if option.get("category") in weapon_categories
        ]
    else:
        equipment_list = get_equipment_options(manor, category=current_category)
    return sort_equipment_options(equipment_list)


def build_categories_with_all(active_categories: Mapping[str, str]) -> dict[str, str]:
    return {"all": "全部", **dict(active_categories)}


def annotate_blueprint_synthesis_options(
    recipes: Iterable[dict[str, Any]],
    *,
    active_categories: Mapping[str, str],
    current_category: str,
    infer_equipment_category: Callable[[str, str | None], str | None],
    to_decompose_category: Callable[[str | None], str | None],
) -> list[dict[str, Any]]:
    normalized_recipes: list[dict[str, Any]] = []
    for recipe in recipes:
        normalized_recipe = dict(recipe)
        result_category = infer_equipment_category(
            str(recipe.get("result_key") or ""),
            str(recipe.get("result_effect_type") or ""),
        )
        merged_result_category = to_decompose_category(result_category)
        normalized_recipe["result_category"] = merged_result_category
        normalized_recipe["result_category_name"] = (
            active_categories.get(merged_result_category, merged_result_category)
            if merged_result_category is not None
            else None
        )
        normalized_recipes.append(normalized_recipe)

    if current_category == "all":
        return normalized_recipes
    return [recipe for recipe in normalized_recipes if recipe.get("result_category") == current_category]


def resolve_decompose_category(current_category: str) -> str | None:
    return None if current_category == "all" else current_category
