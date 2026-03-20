from __future__ import annotations

from typing import Any

from gameplay.services.technology import get_categories, get_martial_technologies_grouped, get_technology_display_data

TECHNOLOGY_TABS = frozenset({"basic", "martial", "production"})
MARTIAL_TROOP_CLASSES = (
    {"key": "dao", "name": "刀类"},
    {"key": "qiang", "name": "枪类"},
    {"key": "jian", "name": "剑类"},
    {"key": "quan", "name": "拳类"},
    {"key": "gong", "name": "弓箭类"},
)
DEFAULT_TECHNOLOGY_TAB = "basic"
DEFAULT_MARTIAL_TROOP_CLASS = "dao"


def normalize_technology_tab(raw_tab: str | None) -> str:
    tab = (raw_tab or DEFAULT_TECHNOLOGY_TAB).strip()
    if tab not in TECHNOLOGY_TABS:
        return DEFAULT_TECHNOLOGY_TAB
    return tab


def normalize_martial_troop_class(raw_troop_class: str | None) -> str:
    troop_class = (raw_troop_class or DEFAULT_MARTIAL_TROOP_CLASS).strip()
    valid_troop_classes = {item["key"] for item in MARTIAL_TROOP_CLASSES}
    if troop_class not in valid_troop_classes:
        return DEFAULT_MARTIAL_TROOP_CLASS
    return troop_class


def get_technology_page_context(
    manor: Any,
    *,
    current_tab: str,
    current_troop_class: str,
) -> dict[str, Any]:
    normalized_tab = normalize_technology_tab(current_tab)
    context: dict[str, Any] = {
        "categories": get_categories(),
        "current_tab": normalized_tab,
    }

    if normalized_tab == "martial":
        all_groups = get_martial_technologies_grouped(manor)
        normalized_troop_class = normalize_martial_troop_class(current_troop_class)
        context["troop_classes"] = list(MARTIAL_TROOP_CLASSES)
        context["current_troop_class"] = normalized_troop_class
        context["martial_groups"] = [group for group in all_groups if group["class_key"] == normalized_troop_class]
        context["technologies"] = []
        return context

    context["martial_groups"] = []
    context["troop_classes"] = []
    context["current_troop_class"] = ""
    context["technologies"] = get_technology_display_data(manor, normalized_tab)
    return context
