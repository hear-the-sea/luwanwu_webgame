from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Callable

from django.conf import settings

from core.utils.yaml_loader import ensure_mapping, load_yaml_data

logger = logging.getLogger(__name__)
TECHNOLOGY_TEMPLATES_PATH = settings.BASE_DIR / "data" / "technology_templates.yaml"


@lru_cache(maxsize=4)
def load_technology_templates(
    load_yaml_data_func: Callable[..., Any] = load_yaml_data,
) -> dict[str, Any]:
    raw = load_yaml_data_func(
        TECHNOLOGY_TEMPLATES_PATH,
        logger=logger,
        context="technology templates",
        default={},
    )
    return ensure_mapping(raw, logger=logger, context="technology templates root")


@lru_cache(maxsize=4)
def build_technology_index(
    load_technology_templates_func: Callable[[], dict[str, Any]] = load_technology_templates,
) -> dict[str, dict[str, Any]]:
    data = load_technology_templates_func()
    result: dict[str, dict[str, Any]] = {}
    for tech in data.get("technologies", []) or []:
        if not isinstance(tech, dict):
            continue
        tech_key = str(tech.get("key") or "").strip()
        if not tech_key:
            continue
        result[tech_key] = tech
    return result


@lru_cache(maxsize=4)
def build_troop_to_class_index(
    load_technology_templates_func: Callable[[], dict[str, Any]] = load_technology_templates,
) -> dict[str, str]:
    data = load_technology_templates_func()
    index: dict[str, str] = {}
    for class_key, class_info in (data.get("troop_classes", {}) or {}).items():
        if not isinstance(class_info, dict):
            continue
        for troop_key in class_info.get("troops", []) or []:
            troop_key_str = str(troop_key).strip()
            if troop_key_str:
                index[troop_key_str] = str(class_key)
    return index


def clear_technology_cache() -> None:
    load_technology_templates.cache_clear()
    build_technology_index.cache_clear()
    build_troop_to_class_index.cache_clear()
