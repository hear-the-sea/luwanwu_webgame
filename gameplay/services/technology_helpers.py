from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence

MARTIAL_TECH_GROUP_ORDER = ("dao", "qiang", "jian", "quan", "gong")


def build_technology_display_entry(
    *,
    tech: Dict[str, Any],
    player_tech,
    calculate_upgrade_cost,
    scale_duration,
) -> Dict[str, Any]:
    tech_key = tech["key"]
    level = player_tech.level if player_tech else 0
    max_level = tech.get("max_level", 10)

    upgrade_cost = calculate_upgrade_cost(tech_key, level) if level < max_level else None
    if level < max_level:
        base_time = tech.get("base_time", 60)
        upgrade_duration = scale_duration(base_time * (1.4**level), minimum=1)
    else:
        upgrade_duration = None

    is_upgrading = player_tech.is_upgrading if player_tech else False
    upgrade_complete_at = player_tech.upgrade_complete_at if player_tech else None
    time_remaining = player_tech.time_remaining if player_tech else 0

    effect_per_level = tech.get("effect_per_level", 0.10)
    current_effect = level * effect_per_level * 100
    next_effect = (level + 1) * effect_per_level * 100 if level < max_level else None

    return {
        "key": tech_key,
        "name": tech["name"],
        "description": tech.get("description", ""),
        "category": tech.get("category"),
        "troop_class": tech.get("troop_class"),
        "effect_type": tech.get("effect_type"),
        "level": level,
        "max_level": max_level,
        "upgrade_cost": upgrade_cost,
        "upgrade_duration": upgrade_duration,
        "current_effect": current_effect,
        "next_effect": next_effect,
        "effect_per_level": effect_per_level,
        "can_upgrade": level < max_level and not is_upgrading,
        "is_upgrading": is_upgrading,
        "upgrade_complete_at": upgrade_complete_at,
        "time_remaining": time_remaining,
    }


def group_martial_technology_entries(
    technologies: Iterable[Dict[str, Any]],
    troop_classes: Dict[str, Any],
    *,
    order: Sequence[str] = MARTIAL_TECH_GROUP_ORDER,
) -> list[Dict[str, Any]]:
    grouped: dict[str, Dict[str, Any]] = {}
    for tech in technologies:
        troop_class = str(tech.get("troop_class") or "")
        if troop_class not in grouped:
            class_info = troop_classes.get(troop_class, {})
            grouped[troop_class] = {
                "class_key": troop_class,
                "class_name": class_info.get("name", troop_class),
                "technologies": [],
            }
        grouped[troop_class]["technologies"].append(tech)

    return [grouped[class_key] for class_key in order if class_key in grouped]


def schedule_technology_completion_task(
    tech,
    eta_seconds: int,
    *,
    logger,
    transaction_module,
    safe_apply_async_func,
) -> None:
    countdown = max(0, int(eta_seconds))
    try:
        from gameplay.tasks import complete_technology_upgrade
    except Exception:
        logger.warning("Unable to import complete_technology_upgrade task; skip scheduling", exc_info=True)
        return

    transaction_module.on_commit(
        lambda: safe_apply_async_func(
            complete_technology_upgrade,
            args=[tech.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_technology_upgrade dispatch failed",
        )
    )


def build_technology_upgrade_response(*, template_name: str, duration: int) -> Dict[str, Any]:
    return {
        "success": True,
        "message": f"{template_name} 开始升级，预计 {duration} 秒后完成",
        "duration": duration,
    }


def resolve_technology_name(template: Dict[str, Any] | None, tech_key: str) -> str:
    return str(template.get("name") or tech_key) if template else tech_key


def send_technology_completion_notification(*, tech, tech_name: str, logger, notify_user_func) -> None:
    from ..models import Message
    from .utils.messages import create_message

    try:
        create_message(
            manor=tech.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{tech_name} 研究完成",
            body=f"当前等级 Lv{tech.level}",
        )
        notify_user_func(
            tech.manor.user_id,
            {
                "kind": "system",
                "title": f"{tech_name} 研究完成",
                "tech_key": tech.tech_key,
                "level": tech.level,
            },
            log_context="technology upgrade notification",
        )
    except Exception as exc:
        logger.warning(
            "technology upgrade notification failed: tech_id=%s manor_id=%s tech_key=%s error=%s",
            getattr(tech, "id", None),
            getattr(tech, "manor_id", None),
            getattr(tech, "tech_key", None),
            exc,
            exc_info=True,
        )
