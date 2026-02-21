from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Set, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async, safe_apply_async_with_dedup

from ...models import Manor, MissionRun, MissionTemplate
from ..messages import create_message
from ..notifications import notify_user
from ..troops import apply_defender_troop_losses
from core.utils.time_scale import scale_duration

from .attempts import get_mission_daily_limit, mission_attempts_today
from .drops import award_mission_drops_locked, resolve_defense_drops_if_missing
from .loadout import normalize_mission_loadout, travel_time_seconds
from .sync_report import generate_sync_battle_report

logger = logging.getLogger(__name__)


_MISSION_REFRESH_DISPATCH_DEDUP_SECONDS = 5


def _normalize_mapping(raw: Any) -> Dict[str, object]:
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_guest_configs(raw: Any) -> List[Any]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    normalized: List[Any] = []
    for entry in raw:
        if isinstance(entry, str):
            key = entry.strip()
            if key:
                normalized.append(key)
        elif isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def _try_dispatch_mission_refresh_task(task, run_id: int) -> bool:
    return safe_apply_async_with_dedup(
        task,
        dedup_key=f"mission:refresh_dispatch:{run_id}",
        dedup_timeout=_MISSION_REFRESH_DISPATCH_DEDUP_SECONDS,
        args=[run_id],
        countdown=0,
        logger=logger,
        log_message=f"mission refresh dispatch failed: run_id={run_id}",
    )


def refresh_mission_runs(manor: Manor, *, prefer_async: bool = False) -> None:
    now = timezone.now()
    due_run_ids = list(
        manor.mission_runs.filter(
            status=MissionRun.Status.ACTIVE,
            return_at__isnull=False,
            return_at__lte=now,
        ).values_list("id", flat=True)
    )
    if not due_run_ids:
        return

    sync_run_ids = due_run_ids
    sync_max_runs = max(0, int(getattr(settings, "MISSION_REFRESH_SYNC_MAX_RUNS", 3)))
    should_try_async = prefer_async or len(due_run_ids) > sync_max_runs

    if should_try_async:
        try:
            from gameplay.tasks import complete_mission_task
        except Exception:
            logger.warning("Failed to import mission task, falling back to sync refresh", exc_info=True)
        else:
            sync_run_ids = []
            for run_id in due_run_ids:
                if not _try_dispatch_mission_refresh_task(complete_mission_task, run_id):
                    sync_run_ids.append(run_id)

            if not sync_run_ids:
                return

    active_runs = list(
        MissionRun.objects.select_related("mission")
        .prefetch_related("guests")
        .filter(id__in=sync_run_ids)
        .order_by("return_at")
    )
    for run in active_runs:
        finalize_mission_run(run, now=now)


def _load_locked_mission_run(run_pk: int) -> MissionRun | None:
    return (
        MissionRun.objects.select_for_update()
        .select_related("mission", "manor", "battle_report")
        .prefetch_related("guests")
        .filter(pk=run_pk)
        .first()
    )


def _build_defense_report_if_needed(locked_run: MissionRun) -> Any:
    report = locked_run.battle_report
    if report or locked_run.is_retreating or not locked_run.mission.is_defense:
        return report

    from ...models import PlayerTroop
    from guests.models import GuestStatus

    defender_guests = list(
        locked_run.manor.guests.select_for_update()
        .filter(status=GuestStatus.IDLE)
        .select_related("template")
        .prefetch_related("skills")
        .order_by("-template__rarity", "-level", "id")
    )
    defender_loadout = {
        troop.troop_template.key: troop.count
        for troop in (
            PlayerTroop.objects.select_for_update()
            .filter(manor=locked_run.manor, count__gt=0)
            .select_related("troop_template")
        )
    }
    report = generate_sync_battle_report(
        manor=locked_run.manor,
        mission=locked_run.mission,
        guests=defender_guests,
        loadout=defender_loadout,
        defender_setup={},
        travel_seconds=0,
        seed=locked_run.id,
    )
    locked_run.battle_report = report
    locked_run.save(update_fields=["battle_report"])
    return report


def _extract_report_guest_state(report: Any, player_side: str) -> Tuple[Dict[int, int], Set[int], Set[int]]:
    hp_updates: Dict[int, int] = {}
    defeated_guest_ids: Set[int] = set()
    participant_ids: Set[int] = set()

    if not report:
        return hp_updates, defeated_guest_ids, participant_ids

    loss_updates = ((report.losses or {}).get(player_side) or {}).get("hp_updates") or {}
    for gid, hp in loss_updates.items():
        try:
            gid_int = int(gid)
            hp_int = int(hp)
        except (TypeError, ValueError):
            continue
        hp_updates[gid_int] = hp_int

    team_entries = report.defender_team if player_side == "defender" else report.attacker_team
    for entry in team_entries or []:
        gid = entry.get("guest_id")
        remaining = entry.get("remaining_hp")
        try:
            gid_int = int(gid)
            remaining_int = int(remaining)
        except (TypeError, ValueError):
            continue
        participant_ids.add(gid_int)
        hp_updates.setdefault(gid_int, remaining_int)
        if remaining_int <= 0:
            defeated_guest_ids.add(gid_int)

    return hp_updates, defeated_guest_ids, participant_ids


def _select_guests_for_finalize(locked_run: MissionRun, report: Any, participant_ids: Set[int]) -> List[Any]:
    if locked_run.is_retreating:
        return list(locked_run.guests.select_for_update())
    if report and participant_ids:
        return list(locked_run.manor.guests.select_for_update().filter(id__in=participant_ids))
    return list(locked_run.guests.select_for_update())


def _prepare_guest_updates_for_finalize(
    guests: List[Any],
    *,
    is_retreating: bool,
    defeated_guest_ids: Set[int],
    hp_updates: Dict[int, int],
    now,
) -> Tuple[List[Any], List[str]]:
    from guests.models import GuestStatus

    guests_to_update: List[Any] = []
    for guest in guests:
        if is_retreating:
            guest.status = GuestStatus.IDLE
        else:
            guest.status = GuestStatus.INJURED if guest.id in defeated_guest_ids else GuestStatus.IDLE
            target_hp = hp_updates.get(guest.id)
            if target_hp is not None:
                guest.current_hp = max(1, min(guest.max_hp, target_hp))
                guest.last_hp_recovery_at = now
        guests_to_update.append(guest)

    fields = ["status"] if is_retreating else ["status", "current_hp", "last_hp_recovery_at"]
    return guests_to_update, fields


def _mark_run_completed(locked_run: MissionRun, now) -> None:
    locked_run.status = MissionRun.Status.COMPLETED
    locked_run.completed_at = now
    locked_run.save(update_fields=["status", "completed_at"])


def _return_attacker_troops_after_mission(locked_run: MissionRun, report: Any) -> None:
    if locked_run.mission.is_defense:
        return

    from ..troops import _return_surviving_troops_batch

    loadout = locked_run.troop_loadout or {}
    if not loadout:
        return

    if locked_run.is_retreating:
        if report:
            logger.warning(
                "撤退但存在战报，按战报归还护院: run_id=%s",
                locked_run.id,
                extra={"run_id": locked_run.id, "manor_id": locked_run.manor.id},
            )
            _return_surviving_troops_batch(locked_run.manor, loadout, report)
            return

        _return_surviving_troops_batch(locked_run.manor, loadout)
        return

    if not report:
        logger.warning(
            "任务完成但无战报，全额归还护院: run_id=%s",
            locked_run.id,
            extra={"run_id": locked_run.id, "manor_id": locked_run.manor.id},
        )
        _return_surviving_troops_batch(locked_run.manor, loadout)
        return

    _return_surviving_troops_batch(locked_run.manor, loadout, report)


def _build_mission_drops_with_salvage(locked_run: MissionRun, report: Any) -> Dict[str, int]:
    drops = dict(report.drops or {})
    if locked_run.mission.is_defense and not drops:
        drops = resolve_defense_drops_if_missing(report, locked_run.mission.drop_table or {})

    try:
        from ..battle_salvage import calculate_battle_salvage

        exp_fruit_count, equipment_recovery = calculate_battle_salvage(report)
        if exp_fruit_count > 0:
            drops["experience_fruit"] = drops.get("experience_fruit", 0) + exp_fruit_count
        for equip_key, count in equipment_recovery.items():
            drops[equip_key] = drops.get(equip_key, 0) + count
    except Exception as exc:
        logger.warning(
            "Failed to calculate mission battle salvage rewards: run_id=%s report_id=%s error=%s",
            locked_run.id,
            getattr(report, "id", None),
            exc,
            exc_info=True,
        )

    return drops


def _apply_mission_rewards_if_won(locked_run: MissionRun, report: Any, player_side: str) -> None:
    if not report:
        return
    if locked_run.is_retreating or report.winner != player_side:
        return

    drops = _build_mission_drops_with_salvage(locked_run, report)
    if not drops:
        return

    report.drops = drops
    report.save(update_fields=["drops"])
    award_mission_drops_locked(locked_run.manor, drops, locked_run.mission.name)


def _send_mission_report_message(locked_run: MissionRun, report: Any) -> None:
    if not report or locked_run.is_retreating:
        return

    create_message(
        manor=locked_run.manor,
        kind="battle",
        title=f"{locked_run.mission.name} 战报",
        body="",
        battle_report=report,
    )
    notify_user(
        locked_run.manor.user_id,
        {
            "kind": "battle",
            "title": f"{locked_run.mission.name} 战报",
            "report_id": report.id,
            "mission_key": locked_run.mission.key,
            "mission_name": locked_run.mission.name,
        },
        log_context="mission battle notification",
    )


def finalize_mission_run(run: MissionRun, now=None) -> None:
    now = now or timezone.now()

    with transaction.atomic():
        locked_run = _load_locked_mission_run(run.pk)
        if not locked_run or locked_run.status == MissionRun.Status.COMPLETED:
            return

        report = _build_defense_report_if_needed(locked_run)
        player_side = "defender" if locked_run.mission.is_defense else "attacker"

        hp_updates, defeated_guest_ids, participant_ids = _extract_report_guest_state(report, player_side)
        guests = _select_guests_for_finalize(locked_run, report, participant_ids)
        guests_to_update, update_fields = _prepare_guest_updates_for_finalize(
            guests,
            is_retreating=locked_run.is_retreating,
            defeated_guest_ids=defeated_guest_ids,
            hp_updates=hp_updates,
            now=now,
        )

        if guests_to_update:
            from guests.models import Guest

            Guest.objects.bulk_update(guests_to_update, update_fields)

        _mark_run_completed(locked_run, now)

        if report and locked_run.mission.is_defense and not locked_run.is_retreating:
            apply_defender_troop_losses(locked_run.manor, report)

        _return_attacker_troops_after_mission(locked_run, report)
        _apply_mission_rewards_if_won(locked_run, report, player_side)
        _send_mission_report_message(locked_run, report)


def _validate_mission_attempts(manor: Manor, mission: MissionTemplate) -> None:
    attempts = mission_attempts_today(manor, mission)
    daily_limit = get_mission_daily_limit(manor, mission)
    if attempts >= daily_limit:
        raise ValueError("今日该任务次数已耗尽")


def _prepare_offense_launch_inputs(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
) -> Tuple[List[Any], Dict[str, int], int]:
    from guests.models import GuestStatus

    guests = list(
        manor.guests.select_for_update()
        .filter(id__in=guest_ids)
        .select_related("template")
        .prefetch_related("skills")
    )
    if len(guests) != len(set(guest_ids)):
        raise ValueError("部分门客不可用或已离开庄园")
    if any(guest.status != GuestStatus.IDLE for guest in guests):
        raise ValueError("部分门客不可用或已离开庄园")
    if not guests:
        raise ValueError("请选择至少一名门客")

    if mission.guest_only:
        loadout: Dict[str, int] = {}
    else:
        loadout = normalize_mission_loadout(troop_loadout)
        from battle.services import validate_troop_capacity

        validate_troop_capacity(guests, loadout)

    if loadout:
        from ..troops import _deduct_troops_batch

        _deduct_troops_batch(manor, loadout)

    travel_seconds = travel_time_seconds(mission.base_travel_time, guests, loadout)
    return guests, loadout, travel_seconds


def _prepare_launch_inputs(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
) -> Tuple[List[Any], Dict[str, int], int]:
    if mission.is_defense:
        return [], {}, scale_duration(mission.base_travel_time, minimum=1)

    return _prepare_offense_launch_inputs(manor, mission, guest_ids, troop_loadout)


def _mark_guests_deployed_if_needed(mission: MissionTemplate, guests: List[Any]) -> None:
    if mission.is_defense or not guests:
        return

    from guests.models import Guest, GuestStatus

    for guest in guests:
        guest.status = GuestStatus.DEPLOYED
    Guest.objects.bulk_update(guests, ["status"])


def _create_mission_run_record(
    manor: Manor,
    mission: MissionTemplate,
    guests: List[Any],
    loadout: Dict[str, int],
    travel_seconds: int,
) -> MissionRun:
    return_seconds = travel_seconds if mission.is_defense else travel_seconds * 2
    run = MissionRun.objects.create(
        manor=manor,
        mission=mission,
        troop_loadout=loadout,
        travel_time=travel_seconds,
        return_at=timezone.now() + timedelta(seconds=return_seconds),
    )
    if not mission.is_defense:
        run.guests.set(guests)
    return run


def _build_defender_setup_and_drop_table(mission: MissionTemplate, loadout: Dict[str, int]) -> Tuple[dict, Dict[str, object]]:
    if mission.is_defense:
        return {"troop_loadout": loadout}, {}

    return (
        {
            "guest_keys": _normalize_guest_configs(mission.enemy_guests),
            "troop_loadout": _normalize_mapping(mission.enemy_troops),
            "technology": _normalize_mapping(mission.enemy_technology),
        },
        _normalize_mapping(mission.drop_table),
    )


def _sync_report_for_launch(
    manor: Manor,
    mission: MissionTemplate,
    guests: List[Any],
    loadout: Dict[str, int],
    defender_setup: dict,
    travel_seconds: int,
    seed,
):
    return generate_sync_battle_report(
        manor=manor,
        mission=mission,
        guests=guests,
        loadout=loadout,
        defender_setup=defender_setup,
        travel_seconds=travel_seconds,
        seed=seed,
    )


def _dispatch_or_sync_launch_report(
    manor: Manor,
    mission: MissionTemplate,
    run: MissionRun,
    guests: List[Any],
    loadout: Dict[str, int],
    defender_setup: dict,
    drop_table: Dict[str, object],
    travel_seconds: int,
    seed,
    generate_report_task,
):
    if mission.is_defense:
        return None

    force_sync = bool(getattr(settings, "DEBUG", False) or os.environ.get("PYTEST_CURRENT_TEST"))
    if force_sync:
        return _sync_report_for_launch(manor, mission, guests, loadout, defender_setup, travel_seconds, seed)

    ok = safe_apply_async(
        generate_report_task,
        kwargs={
            "manor_id": manor.id,
            "mission_id": mission.id,
            "run_id": run.id,
            "guest_ids": [g.id for g in guests],
            "troop_loadout": loadout,
            "fill_default_troops": False,
            "battle_type": mission.battle_type or "task",
            "opponent_name": mission.name,
            "defender_setup": defender_setup,
            "drop_table": drop_table,
            "travel_seconds": travel_seconds,
            "seed": seed,
        },
        logger=logger,
        log_message="generate_report_task dispatch failed; falling back to sync generation",
    )
    if ok:
        return None

    return _sync_report_for_launch(manor, mission, guests, loadout, defender_setup, travel_seconds, seed)


def _attach_run_report_if_empty(run: MissionRun, report: Any) -> None:
    if not report:
        return

    updated = MissionRun.objects.filter(pk=run.pk, battle_report__isnull=True).update(battle_report=report)
    if updated:
        run.battle_report = report


def _schedule_mission_completion_task(run: MissionRun, complete_mission_task) -> None:
    if run.return_at is None:
        raise RuntimeError("Mission run was not created correctly")

    countdown = max(0, int((run.return_at - timezone.now()).total_seconds()))
    safe_apply_async(
        complete_mission_task,
        args=[run.id],
        countdown=countdown,
        logger=logger,
        log_message="complete_mission_task dispatch failed; relying on refresh_mission_runs",
    )


def launch_mission(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
    seed=None,
):
    refresh_mission_runs(manor)
    _validate_mission_attempts(manor, mission)

    with transaction.atomic():
        # Lock manor to prevent concurrent mission launches bypassing limits
        Manor.objects.select_for_update().get(pk=manor.pk)
        # Re-validate inside lock
        _validate_mission_attempts(manor, mission)

        guests, loadout, travel_seconds = _prepare_launch_inputs(manor, mission, guest_ids, troop_loadout)
        _mark_guests_deployed_if_needed(mission, guests)
        run = _create_mission_run_record(manor, mission, guests, loadout, travel_seconds)

    try:
        from battle.tasks import generate_report_task
        from gameplay.tasks import complete_mission_task

        defender_setup, drop_table = _build_defender_setup_and_drop_table(mission, loadout)
        report = _dispatch_or_sync_launch_report(
            manor,
            mission,
            run,
            guests,
            loadout,
            defender_setup,
            drop_table,
            travel_seconds,
            seed,
            generate_report_task,
        )
        _attach_run_report_if_empty(run, report)
        _schedule_mission_completion_task(run, complete_mission_task)
        return run
    except ValueError as exc:
        logger.warning(
            "launch_mission validation failed: %s",
            exc,
            extra={"manor_id": manor.id, "mission_id": mission.id},
        )
        raise
    except Exception as exc:
        logger.exception(
            "launch_mission unexpected error",
            extra={"manor_id": manor.id, "mission_id": mission.id, "error": str(exc)},
        )
        raise


def schedule_mission_completion(run: MissionRun) -> None:
    from gameplay.tasks import complete_mission_task

    if not run.return_at:
        return
    countdown = max(0, int((run.return_at - timezone.now()).total_seconds()))
    safe_apply_async(
        complete_mission_task,
        args=[run.id],
        countdown=countdown,
        logger=logger,
        log_message="complete_mission_task dispatch failed; relying on refresh_mission_runs",
    )


def request_retreat(run: MissionRun) -> None:
    if run.status != MissionRun.Status.ACTIVE:
        raise ValueError("任务已结束，无法撤退")
    now = timezone.now()
    outbound_finish = run.started_at + timedelta(seconds=run.travel_time)
    if now >= outbound_finish:
        raise ValueError("已进入返程，无法撤退")
    elapsed = max(0, int((now - run.started_at).total_seconds()))
    return_time = max(1, elapsed)
    run.is_retreating = True
    run.return_at = now + timedelta(seconds=return_time)
    run.save(update_fields=["is_retreating", "return_at"])
    schedule_mission_completion(run)


def can_retreat(run: MissionRun, now=None) -> bool:
    if run.status != MissionRun.Status.ACTIVE:
        return False
    if run.is_retreating:
        return False
    now = now or timezone.now()
    outbound_finish = run.started_at + timedelta(seconds=run.travel_time)
    return now < outbound_finish
