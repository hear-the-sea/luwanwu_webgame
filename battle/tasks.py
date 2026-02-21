from __future__ import annotations

import logging

from celery import shared_task
from django.apps import apps

from guests.models import Guest

from .services import simulate_report

logger = logging.getLogger(__name__)


def _normalize_enemy_technology_config(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_mapping(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_guest_configs(raw) -> list[str | dict]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    normalized: list[str | dict] = []
    for entry in raw:
        if isinstance(entry, str):
            key = entry.strip()
            if key:
                normalized.append(key)
        elif isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def _normalize_troop_loadout(raw) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in raw.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        try:
            qty = int(value)
        except (TypeError, ValueError):
            qty = 0
        normalized[key_str] = max(0, qty)
    return normalized


def _coerce_enemy_guest_level(config: dict, default: int = 50) -> int:
    try:
        level = int(config.get("guest_level", default))
    except (TypeError, ValueError):
        level = default
    return max(1, level)


def _normalize_guest_skills(config: dict) -> list[str] | None:
    raw = config.get("guest_skills")
    if not isinstance(raw, (list, tuple, set)):
        return None
    skills = [str(item).strip() for item in raw if str(item).strip()]
    return skills or None


@shared_task(
    name="battle.generate_report",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=120,
    time_limit=180,
)
def generate_report_task(
    self,
    manor_id: int,
    mission_id: int | None,
    run_id: int | None,
    guest_ids: list[int],
    troop_loadout: dict,
    battle_type: str,
    fill_default_troops: bool = True,
    opponent_name: str | None = None,
    defender_setup: dict | None = None,
    drop_table: dict | None = None,
    travel_seconds: int | None = None,
    seed: int | None = None,
):
    """
    Generate a BattleReport asynchronously and attach it to MissionRun if provided.

    Features:
    - Automatic retry on failure (max 3 attempts)
    - Soft time limit (120s) and hard limit (180s)
    - Comprehensive error handling and logging
    """
    try:
        Manor = apps.get_model("gameplay", "Manor")
        MissionTemplate = apps.get_model("gameplay", "MissionTemplate")

        if run_id:
            MissionRun = apps.get_model("gameplay", "MissionRun")

            row = MissionRun.objects.filter(pk=run_id).values("battle_report_id").first()
            if row is None:
                logger.warning("MissionRun %s not found; skipping battle report generation", run_id)
                return None
            existing_report_id = row.get("battle_report_id")
            if existing_report_id:
                logger.info(
                    "MissionRun %s already has battle_report %s; skipping generation",
                    run_id,
                    existing_report_id,
                )
                return int(existing_report_id)

        # Fetch manor with error handling
        try:
            manor = Manor.objects.select_related("user").get(pk=manor_id)
        except Manor.DoesNotExist:
            logger.error("Manor %d not found for battle report generation", manor_id)
            # Don't retry if manor doesn't exist
            return None

        mission = MissionTemplate.objects.filter(pk=mission_id).first() if mission_id else None
        guests = list(Guest.objects.filter(id__in=guest_ids).select_related("template").prefetch_related("skills"))

        if mission and mission.is_defense:
            from battle.combatants import build_named_ai_guests
            from core.game_data.technology import get_guest_stat_bonuses, resolve_enemy_tech_levels

            tech_conf = _normalize_enemy_technology_config(mission.enemy_technology)
            attacker_guest_level = _coerce_enemy_guest_level(tech_conf)
            attacker_guests = build_named_ai_guests(
                _normalize_guest_configs(mission.enemy_guests), level=attacker_guest_level
            )
            attacker_tech_levels = resolve_enemy_tech_levels(tech_conf)
            attacker_guest_bonuses = get_guest_stat_bonuses(tech_conf)
            attacker_guest_skills = _normalize_guest_skills(tech_conf)
            enemy_troops = _normalize_troop_loadout(mission.enemy_troops)

            report = simulate_report(
                manor=manor,
                battle_type=battle_type,
                seed=seed,
                troop_loadout=enemy_troops,
                fill_default_troops=False,
                attacker_guests=attacker_guests,
                defender_setup={"troop_loadout": troop_loadout},
                defender_guests=guests,
                defender_max_squad=len(guests) if guests else None,
                drop_table={},
                opponent_name=opponent_name or mission.name,
                travel_seconds=travel_seconds,
                send_message=False,
                auto_reward=False,
                drop_handler=None,
                max_squad=len(attacker_guests) if attacker_guests else None,
                apply_damage=False,
                use_lock=False,  # 修复：门客已DEPLOYED，不需要锁校验
                attacker_tech_levels=attacker_tech_levels,
                attacker_guest_bonuses=attacker_guest_bonuses or None,
                attacker_guest_skills=attacker_guest_skills,
                attacker_manor=None,
            )
        else:
            report = simulate_report(
                manor=manor,
                battle_type=battle_type,
                seed=seed,
                troop_loadout=troop_loadout,
                fill_default_troops=fill_default_troops,
                attacker_guests=guests,
                defender_setup=defender_setup,
                drop_table=_normalize_mapping(drop_table),
                opponent_name=opponent_name or (mission.name if mission else None),
                travel_seconds=travel_seconds,
                send_message=False,
                auto_reward=False,
                drop_handler=None,
                max_squad=getattr(manor, "max_squad_size", None),
                apply_damage=False,
                use_lock=False,  # 修复：门客已DEPLOYED，不需要锁校验
            )

        if run_id:
            MissionRun = apps.get_model("gameplay", "MissionRun")
            # 保留原始出征时间，仅写入战报
            MissionRun.objects.filter(pk=run_id, battle_report__isnull=True).update(battle_report=report)

        logger.info("Battle report %d generated successfully for manor %d", report.pk, manor_id)
        return report.pk

    except ValueError as exc:
        # Business/validation errors should not be retried.
        logger.warning(
            "Battle report generation aborted (non-retriable) for manor %s: %s",
            manor_id,
            exc,
            extra={"manor_id": manor_id, "run_id": run_id, "mission_id": mission_id},
        )
        return None
    except Exception as exc:
        logger.exception(
            f"Battle report generation failed for manor {manor_id}: {exc}",
            extra={"manor_id": manor_id, "run_id": run_id, "mission_id": mission_id},
        )
        # Retry on unexpected errors
        raise self.retry(exc=exc)
