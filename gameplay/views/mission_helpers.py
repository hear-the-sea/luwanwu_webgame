from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_int, sanitize_error_message
from core.utils.cache_lock import acquire_best_effort_lock, release_best_effort_lock
from gameplay.models import MissionTemplate

logger = logging.getLogger(__name__)

MISSION_CARD_KEY = "mission_card"
MISSION_ACTION_LOCK_SECONDS = 5
_LOCAL_LOCK_PREFIX = "local:"


def handle_unexpected_mission_error(
    request: HttpRequest,
    exc: Exception,
    *,
    log_message: str,
    log_args: tuple[object, ...],
    logger_instance: logging.Logger | None = None,
) -> None:
    flash_unexpected_view_error(
        request,
        exc,
        log_message=log_message,
        log_args=log_args,
        logger_instance=logger_instance or logger,
    )


def handle_known_mission_error(request: HttpRequest, exc: GameError | ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


def normalize_mission_key(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    mission_key = str(raw_value).strip()
    return mission_key or None


def mission_tasks_url(mission_key: str | None = None) -> str:
    base_url = reverse("gameplay:tasks")
    if mission_key:
        return f"{base_url}?mission={mission_key}"
    return base_url


def mission_tasks_redirect(mission_key: str | None = None) -> HttpResponse:
    return redirect(mission_tasks_url(mission_key))


def resolve_mission_or_redirect(
    request: HttpRequest, mission_key_raw: Any
) -> tuple[MissionTemplate | None, HttpResponse | None]:
    mission_key = normalize_mission_key(mission_key_raw)
    if mission_key is None:
        messages.error(request, "请选择任务")
        return None, mission_tasks_redirect()

    mission = MissionTemplate.objects.filter(key=mission_key).first()
    if mission is None:
        messages.error(request, "任务不存在")
        return None, mission_tasks_redirect(mission_key)

    return mission, None


def parse_positive_ids(raw_values: list[str]) -> list[int] | None:
    if not raw_values:
        return []

    parsed: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        value = safe_int(raw, default=None)
        if value is None or value <= 0:
            return None
        if value in seen:
            continue
        parsed.append(value)
        seen.add(value)
    return parsed


def mission_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return f"mission:view_lock:{action}:{manor_id}:{scope}"


def acquire_mission_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    key = mission_action_lock_key(action, manor_id, scope)
    acquired, from_cache, lock_token = acquire_best_effort_lock(
        key,
        timeout_seconds=MISSION_ACTION_LOCK_SECONDS,
        logger=logger,
        log_context="mission action lock",
    )
    if not acquired:
        return False, "", None
    if from_cache:
        return True, key, lock_token
    return True, f"{_LOCAL_LOCK_PREFIX}{key}", lock_token


def release_mission_action_lock(lock_key: str, lock_token: str | None) -> None:
    if not lock_key:
        return
    if lock_key.startswith(_LOCAL_LOCK_PREFIX):
        release_best_effort_lock(
            lock_key[len(_LOCAL_LOCK_PREFIX) :],
            from_cache=False,
            lock_token=lock_token,
            logger=logger,
            log_context="mission action lock",
        )
        return
    release_best_effort_lock(
        lock_key,
        from_cache=True,
        lock_token=lock_token,
        logger=logger,
        log_context="mission action lock",
    )


def collect_mission_asset_keys(missions: list[MissionTemplate]) -> tuple[set[str], set[str], set[str]]:
    enemy_keys: set[str] = set()
    troop_keys: set[str] = set()
    drop_keys: set[str] = set()

    for mission in missions:
        for entry in mission.enemy_guests or []:
            if isinstance(entry, str):
                enemy_keys.add(entry)
            elif isinstance(entry, dict):
                key = entry.get("key")
                if key:
                    enemy_keys.add(key)
        troop_keys.update((mission.enemy_troops or {}).keys())
        drop_keys.update((mission.drop_table or {}).keys())
        drop_keys.update((mission.probability_drop_table or {}).keys())
        for drop_value in (mission.drop_table or {}).values():
            if not isinstance(drop_value, dict):
                continue
            choices = drop_value.get("choices")
            if not isinstance(choices, list):
                continue
            for choice in choices:
                if isinstance(choice, str):
                    choice_key = choice.strip()
                elif isinstance(choice, dict):
                    choice_key = str(
                        choice.get("key") or choice.get("item_key") or choice.get("template_key") or ""
                    ).strip()
                else:
                    continue
                if choice_key:
                    drop_keys.add(choice_key)

    return enemy_keys, troop_keys, drop_keys


def parse_drop_value(value: Any) -> tuple[float | None, int | None]:
    chance = None
    count = None
    if isinstance(value, dict):
        raw_chance = value.get("chance", value.get("probability"))
        raw_count = value.get("count", value.get("quantity", value.get("amount")))
        try:
            chance = float(raw_chance) if raw_chance is not None else None
        except (TypeError, ValueError):
            chance = None
        try:
            count = int(raw_count) if raw_count is not None else None
        except (TypeError, ValueError):
            count = None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = None
        if number is not None and 0 < number < 1:
            chance = number
            count = 1
        elif number is not None and number >= 1:
            count = int(number)

    if chance is not None and count is None:
        count = 1
    return chance, count


def resolve_drop_label(
    key: str,
    drop_labels: dict[str, str],
    item_templates: dict[str, Any],
    book_labels: dict[str, str],
) -> str:
    label = drop_labels.get(key, key)
    if label != key:
        return label
    tpl = item_templates.get(key)
    if tpl:
        return tpl.name
    if key in book_labels:
        return book_labels[key]
    return key


def resolve_drop_pool_label(
    value: Any,
    drop_labels: dict[str, str],
    item_templates: dict[str, Any],
    book_labels: dict[str, str],
) -> str | None:
    if not isinstance(value, dict):
        return None
    choices = value.get("choices")
    if not isinstance(choices, list):
        return None

    labels: list[str] = []
    for choice in choices:
        if isinstance(choice, str):
            choice_key = choice.strip()
        elif isinstance(choice, dict):
            choice_key = str(choice.get("key") or choice.get("item_key") or choice.get("template_key") or "").strip()
        else:
            continue
        if not choice_key:
            continue
        labels.append(resolve_drop_label(choice_key, drop_labels, item_templates, book_labels))

    if not labels:
        return None
    return "/".join(labels)


def resolve_drop_pool_rarity(value: Any, loot_rarities: dict[str, str]) -> str | None:
    if not isinstance(value, dict):
        return None
    choices = value.get("choices")
    if not isinstance(choices, list):
        return None

    rarities: list[str] = []
    for choice in choices:
        if isinstance(choice, str):
            choice_key = choice.strip()
        elif isinstance(choice, dict):
            choice_key = str(choice.get("key") or choice.get("item_key") or choice.get("template_key") or "").strip()
        else:
            continue
        rarity = loot_rarities.get(choice_key)
        if rarity:
            rarities.append(rarity)

    if not rarities:
        return None
    if len(set(rarities)) == 1:
        return rarities[0]
    return "default"


def iter_choice_pool_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    choices = value.get("choices")
    if not isinstance(choices, list):
        return []

    keys: list[str] = []
    for choice in choices:
        if isinstance(choice, str):
            choice_key = choice.strip()
        elif isinstance(choice, dict):
            choice_key = str(choice.get("key") or choice.get("item_key") or choice.get("template_key") or "").strip()
        else:
            continue
        if choice_key:
            keys.append(choice_key)
    return keys


def build_drop_lists(
    selected_mission: MissionTemplate,
    drop_labels: dict[str, str],
    item_templates: dict[str, Any],
    book_labels: dict[str, str],
    loot_rarities: dict[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    guaranteed_drops: list[dict[str, str]] = []
    probability_drops: list[dict[str, str]] = []
    handled_probability_keys: set[str] = set()

    for key, val in (selected_mission.drop_table or {}).items():
        if isinstance(val, dict) and val.get("choices") and (selected_mission.probability_drop_table or {}):
            for choice_key in iter_choice_pool_keys(val):
                if choice_key not in (selected_mission.probability_drop_table or {}):
                    continue
                handled_probability_keys.add(choice_key)
                label = resolve_drop_label(choice_key, drop_labels, item_templates, book_labels)
                _, count = parse_drop_value((selected_mission.probability_drop_table or {}).get(choice_key))
                rarity = loot_rarities.get(choice_key) or "default"
                display_label = f"{label} x{count}" if (count is not None and count >= 1) else label
                probability_drops.append({"label": display_label, "rarity": rarity})
            continue
        label = resolve_drop_pool_label(val, drop_labels, item_templates, book_labels) or resolve_drop_label(
            key,
            drop_labels,
            item_templates,
            book_labels,
        )
        chance, count = parse_drop_value(val)
        rarity = resolve_drop_pool_rarity(val, loot_rarities) or loot_rarities.get(key) or "default"

        is_choice_pool = resolve_drop_pool_label(val, drop_labels, item_templates, book_labels) is not None
        if count is not None and count >= 1 and not (is_choice_pool and count == 1):
            display_label = f"{label} x{count}"
        else:
            display_label = label
        if chance is not None and 0 < chance < 1:
            probability_drops.append({"label": display_label, "rarity": rarity})
        else:
            guaranteed_drops.append({"label": display_label, "rarity": rarity})

    for key, val in (selected_mission.probability_drop_table or {}).items():
        if key in handled_probability_keys:
            continue
        label = resolve_drop_label(key, drop_labels, item_templates, book_labels)
        _, count = parse_drop_value(val)
        display_label = f"{label} x{count}" if (count is not None and count >= 1) else label
        rarity = loot_rarities.get(key) or "default"
        probability_drops.append({"label": display_label, "rarity": rarity})

    return guaranteed_drops, probability_drops


def build_mission_data(
    missions: list[MissionTemplate],
    attempts: dict[str, int],
    extra_attempts: dict[str, int],
) -> list[dict[str, Any]]:
    mission_data: list[dict[str, Any]] = []
    for mission in missions:
        used = attempts.get(mission.key, 0)
        extra = extra_attempts.get(mission.key, 0)
        daily_limit = mission.daily_limit + extra
        remaining = max(0, daily_limit - used)
        mission_data.append(
            {
                "mission": mission,
                "used": used,
                "remaining": remaining,
                "daily_limit": daily_limit,
                "extra": extra,
            }
        )
    return mission_data


def build_selection_summary(
    selected_key: str | None,
    missions_by_key: dict[str, MissionTemplate],
    attempts: dict[str, int],
    extra_attempts: dict[str, int],
) -> tuple[MissionTemplate | None, int, int, int]:
    selected_mission = missions_by_key.get(selected_key) if selected_key else None
    selected_attempts = attempts.get(selected_key, 0) if selected_key else 0
    selected_extra = extra_attempts.get(selected_key, 0) if selected_key else 0
    selected_daily_limit = (selected_mission.daily_limit + selected_extra) if selected_mission else 0
    selected_remaining = max(0, selected_daily_limit - selected_attempts)
    return selected_mission, selected_attempts, selected_daily_limit, selected_remaining


def build_troop_config() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    from battle.troops import load_troop_templates

    troop_templates = load_troop_templates()
    troop_template_items = sorted(
        troop_templates.items(),
        key=lambda item: safe_int(item[1].get("priority"), default=0) or 0,
    )
    config_items = [
        {
            "key": key,
            "label": data.get("label", key),
            "description": data.get("description", "") or "",
            "value": 0,
        }
        for key, data in troop_template_items
    ]
    return troop_templates, config_items
