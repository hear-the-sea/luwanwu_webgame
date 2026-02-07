from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Dict, List

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async

from ...models import Manor, MissionRun, MissionTemplate
from ..messages import create_message
from ..notifications import notify_user
from ..troops import apply_defender_troop_losses
from core.utils.time_scale import scale_duration

from .attempts import get_mission_daily_limit, mission_attempts_today
from .drops import award_mission_drops, resolve_defense_drops_if_missing
from .loadout import normalize_mission_loadout, travel_time_seconds
from .sync_report import generate_sync_battle_report

logger = logging.getLogger(__name__)


def refresh_mission_runs(manor: Manor) -> None:
    now = timezone.now()
    active_runs = list(
        manor.mission_runs.select_related("mission")
        .prefetch_related("guests")
        .filter(status=MissionRun.Status.ACTIVE, return_at__isnull=False, return_at__lte=now)
    )
    if not active_runs:
        return
    for run in active_runs:
        finalize_mission_run(run, now=now)


def finalize_mission_run(run: MissionRun, now=None) -> None:
    now = now or timezone.now()

    from guests.models import Guest, GuestStatus

    with transaction.atomic():
        locked_run = (
            MissionRun.objects.select_for_update()
            .select_related("mission", "manor", "battle_report")
            .prefetch_related("guests")
            .filter(pk=run.pk)
            .first()
        )
        if not locked_run or locked_run.status == MissionRun.Status.COMPLETED:
            return

        report = locked_run.battle_report
        player_side = "defender" if locked_run.mission.is_defense else "attacker"
        if not report and (not locked_run.is_retreating) and locked_run.mission.is_defense:
            from ...models import PlayerTroop

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

        hp_updates: Dict[int, int] = {}
        defeated_guest_ids: set[int] = set()
        participant_ids: set[int] = set()
        if report:
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

        if locked_run.is_retreating:
            guests = list(locked_run.guests.select_for_update())
        elif report and participant_ids:
            guests = list(locked_run.manor.guests.select_for_update().filter(id__in=participant_ids))
        else:
            guests = list(locked_run.guests.select_for_update())

        guests_to_update = []
        for guest in guests:
            if locked_run.is_retreating:
                guest.status = GuestStatus.IDLE
            else:
                guest.status = GuestStatus.INJURED if guest.id in defeated_guest_ids else GuestStatus.IDLE
                target_hp = hp_updates.get(guest.id)
                if target_hp is not None:
                    guest.current_hp = max(1, min(guest.max_hp, target_hp))
                    guest.last_hp_recovery_at = now
            guests_to_update.append(guest)

        if guests_to_update:
            if locked_run.is_retreating:
                Guest.objects.bulk_update(guests_to_update, ["status"])
            else:
                Guest.objects.bulk_update(guests_to_update, ["status", "current_hp", "last_hp_recovery_at"])

        locked_run.status = MissionRun.Status.COMPLETED
        locked_run.completed_at = now
        locked_run.save(update_fields=["status", "completed_at"])

        if report and locked_run.mission.is_defense and not locked_run.is_retreating:
            apply_defender_troop_losses(locked_run.manor, report)

        if not locked_run.mission.is_defense:
            from ..troops import _return_surviving_troops_batch

            loadout = locked_run.troop_loadout or {}
            if loadout:
                if locked_run.is_retreating:
                    if report:
                        logger.warning(
                            "撤退但存在战报，按战报归还护院: run_id=%s",
                            locked_run.id,
                            extra={"run_id": locked_run.id, "manor_id": locked_run.manor.id},
                        )
                        _return_surviving_troops_batch(locked_run.manor, loadout, report)
                    else:
                        _return_surviving_troops_batch(locked_run.manor, loadout)
                elif not report:
                    logger.warning(
                        "任务完成但无战报，全额归还护院: run_id=%s",
                        locked_run.id,
                        extra={"run_id": locked_run.id, "manor_id": locked_run.manor.id},
                    )
                    _return_surviving_troops_batch(locked_run.manor, loadout)
                else:
                    _return_surviving_troops_batch(locked_run.manor, loadout, report)

        player_won = False
        if report:
            player_won = (not locked_run.is_retreating) and report.winner == player_side

        if report and player_won:
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

            if drops:
                report.drops = drops
                report.save(update_fields=["drops"])
                award_mission_drops(locked_run.manor, drops, locked_run.mission.name)

        if report and not locked_run.is_retreating:
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


def launch_mission(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
    seed=None,
):
    refresh_mission_runs(manor)
    attempts = mission_attempts_today(manor, mission)
    daily_limit = get_mission_daily_limit(manor, mission)
    if attempts >= daily_limit:
        raise ValueError("今日该任务次数已耗尽")

    from guests.models import Guest, GuestStatus

    run: MissionRun | None = None
    with transaction.atomic():
        if mission.is_defense:
            guests: list = []
            loadout: Dict[str, int] = {}
            travel_seconds = scale_duration(mission.base_travel_time, minimum=1)
        else:
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
                loadout = {}
            else:
                loadout = normalize_mission_loadout(troop_loadout)
                from battle.services import validate_troop_capacity

                validate_troop_capacity(guests, loadout)

            if loadout:
                from ..troops import _deduct_troops_batch

                _deduct_troops_batch(manor, loadout)

            travel_seconds = travel_time_seconds(mission.base_travel_time, guests, loadout)

        if not mission.is_defense and guests:
            for guest in guests:
                guest.status = GuestStatus.DEPLOYED
            Guest.objects.bulk_update(guests, ["status"])

        run = MissionRun.objects.create(
            manor=manor,
            mission=mission,
            troop_loadout=loadout,
            travel_time=travel_seconds,
            return_at=timezone.now() + timedelta(seconds=travel_seconds if mission.is_defense else travel_seconds * 2),
        )
        if not mission.is_defense:
            run.guests.set(guests)

    try:
        from battle.tasks import generate_report_task
        from gameplay.tasks import complete_mission_task

        if mission.is_defense:
            defender_setup: dict = {"troop_loadout": loadout}
            drop_table: Dict[str, object] = {}
        else:
            defender_setup = {
                "guest_keys": mission.enemy_guests or [],
                "troop_loadout": mission.enemy_troops or {},
                "technology": mission.enemy_technology or {},
            }
            drop_table = dict(mission.drop_table or {})

        if run is None or run.return_at is None:
            raise RuntimeError("Mission run was not created correctly")

        def _sync_report():
            return generate_sync_battle_report(
                manor=manor,
                mission=mission,
                guests=guests,
                loadout=loadout,
                defender_setup=defender_setup,
                travel_seconds=travel_seconds,
                seed=seed,
            )

        report = None
        if not mission.is_defense:
            force_sync = bool(getattr(settings, "DEBUG", False) or os.environ.get("PYTEST_CURRENT_TEST"))
            if force_sync:
                report = _sync_report()
            else:
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
                if not ok:
                    report = _sync_report()

        if report:
            updated = MissionRun.objects.filter(pk=run.pk, battle_report__isnull=True).update(battle_report=report)
            if updated:
                run.battle_report = report

        countdown = max(0, int((run.return_at - timezone.now()).total_seconds()))
        safe_apply_async(
            complete_mission_task,
            args=[run.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_mission_task dispatch failed; relying on refresh_mission_runs",
        )
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
