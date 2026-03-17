from __future__ import annotations

import logging
import os
from functools import partial
from typing import Any, Dict, List

from django.conf import settings
from django.utils import timezone

from common.utils.celery import safe_apply_async, safe_apply_async_with_dedup
from core.utils.time_scale import scale_duration
from guests.query_utils import guest_template_rarity_rank_case

from ...models import Manor, MissionRun, MissionTemplate
from ..battle_snapshots import build_guest_battle_snapshots, build_guest_snapshot_proxies
from ..recruitment.troops import apply_defender_troop_losses
from ..utils.messages import create_message
from ..utils.notifications import notify_user
from .drops import award_mission_drops_locked, resolve_defense_drops_if_missing
from .finalization_helpers import (
    apply_mission_rewards_if_won,
    build_defense_report_if_needed,
    build_mission_drops_with_salvage,
    extract_report_guest_state,
    prepare_guest_updates_for_finalize,
    return_attacker_troops_after_mission,
    select_guests_for_finalize,
    send_mission_report_message,
)
from .finalize_command import finalize_mission_run as _finalize_mission_run_command
from .launch_command import launch_mission as _launch_mission_command
from .launch_post_actions import (
    attach_run_report_if_empty,
    build_defender_setup_and_drop_table,
    dispatch_or_sync_launch_report,
    import_launch_post_action_tasks,
    schedule_mission_completion_task,
)
from .refresh_command import refresh_mission_runs as _refresh_mission_runs_command
from .refresh_command import schedule_mission_completion as _schedule_mission_completion_command
from .retreat_command import can_retreat as _can_retreat_command
from .retreat_command import request_retreat as _request_retreat_command
from .sync_report import generate_sync_battle_report

logger = logging.getLogger(__name__)


_MISSION_REFRESH_DISPATCH_DEDUP_SECONDS = 5
MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS = (ConnectionError, OSError, TimeoutError)


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
    _refresh_mission_runs_command(
        manor,
        prefer_async=prefer_async,
        mission_run_model=MissionRun,
        settings_obj=settings,
        logger=logger,
        now_func=timezone.now,
        try_dispatch_mission_refresh_task=_try_dispatch_mission_refresh_task,
        finalize_mission_run=finalize_mission_run,
    )


def _load_locked_mission_run(run_pk: int) -> MissionRun | None:
    return (
        MissionRun.objects.select_for_update()
        .select_related("mission", "manor", "battle_report")
        .prefetch_related("guests")
        .filter(pk=run_pk)
        .first()
    )


def _mark_run_completed(locked_run: MissionRun, now) -> None:
    locked_run.status = MissionRun.Status.COMPLETED
    locked_run.completed_at = now
    locked_run.save(update_fields=["status", "completed_at"])


def _build_mission_drops_with_salvage(locked_run: MissionRun, report: Any, player_side: str) -> Dict[str, int]:
    return build_mission_drops_with_salvage(
        locked_run,
        report,
        player_side,
        logger=logger,
        resolve_defense_drops_if_missing=resolve_defense_drops_if_missing,
    )


def finalize_mission_run(run: MissionRun, now=None) -> None:
    _finalize_mission_run_command(
        run,
        now=now,
        load_locked_mission_run=_load_locked_mission_run,
        build_defense_report_if_needed=partial(
            build_defense_report_if_needed,
            guest_template_rarity_rank_case=guest_template_rarity_rank_case,
            generate_sync_battle_report=generate_sync_battle_report,
        ),
        extract_report_guest_state=extract_report_guest_state,
        select_guests_for_finalize=select_guests_for_finalize,
        prepare_guest_updates_for_finalize=prepare_guest_updates_for_finalize,
        mark_run_completed=_mark_run_completed,
        apply_defender_troop_losses=apply_defender_troop_losses,
        return_attacker_troops_after_mission=partial(return_attacker_troops_after_mission, logger=logger),
        apply_mission_rewards_if_won=partial(
            apply_mission_rewards_if_won,
            logger=logger,
            resolve_defense_drops_if_missing=resolve_defense_drops_if_missing,
            award_mission_drops_locked=award_mission_drops_locked,
        ),
        send_mission_report_message=partial(
            send_mission_report_message,
            logger=logger,
            create_message=create_message,
            notify_user=notify_user,
            notification_infrastructure_exceptions=MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS,
        ),
    )


def _schedule_mission_completion_task(run: MissionRun, complete_mission_task) -> None:
    schedule_mission_completion_task(
        run,
        complete_mission_task,
        safe_apply_async=safe_apply_async,
        logger=logger,
        finalize_mission_run=finalize_mission_run,
        now_func=timezone.now,
    )


def _import_launch_post_action_tasks() -> tuple[Any | None, Any | None]:
    return import_launch_post_action_tasks(logger=logger)


def _try_prepare_launch_report(
    manor: Manor,
    mission: MissionTemplate,
    run: MissionRun,
    guests: List[Any],
    loadout: Dict[str, int],
    travel_seconds: int,
    seed,
    generate_report_task,
) -> None:
    try:
        defender_setup, drop_table = build_defender_setup_and_drop_table(
            mission,
            loadout,
            normalize_guest_configs=_normalize_guest_configs,
            normalize_mapping=_normalize_mapping,
        )
        report = dispatch_or_sync_launch_report(
            manor,
            mission,
            run,
            guests,
            loadout,
            defender_setup,
            drop_table,
            travel_seconds,
            seed,
            generate_report_task=generate_report_task,
            build_guest_snapshot_proxies=build_guest_snapshot_proxies,
            build_guest_battle_snapshots=build_guest_battle_snapshots,
            generate_sync_battle_report=generate_sync_battle_report,
            safe_apply_async=safe_apply_async,
            logger=logger,
            force_sync=bool(getattr(settings, "DEBUG", False) or os.environ.get("PYTEST_CURRENT_TEST")),
        )
        attach_run_report_if_empty(run, report, mission_run_model=MissionRun)
    except Exception:
        logger.error(
            "Mission launch report preparation failed: run_id=%s manor_id=%s mission_id=%s",
            run.id,
            manor.id,
            mission.id,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "mission_launch_report",
                "run_id": run.id,
                "manor_id": manor.id,
                "mission_id": mission.id,
            },
        )


def _dispatch_complete_mission_task(run: MissionRun, complete_mission_task) -> None:
    if complete_mission_task is None:
        logger.error(
            "Mission completion task unavailable after launch: run_id=%s manor_id=%s",
            run.id,
            run.manor_id,
            extra={
                "degraded": True,
                "component": "mission_completion_dispatch",
                "run_id": run.id,
                "manor_id": run.manor_id,
            },
        )
        return

    try:
        _schedule_mission_completion_task(run, complete_mission_task)
    except Exception:
        logger.error(
            "Mission completion dispatch failed after launch: run_id=%s manor_id=%s",
            run.id,
            run.manor_id,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "mission_completion_dispatch",
                "run_id": run.id,
                "manor_id": run.manor_id,
            },
        )


def launch_mission(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
    seed=None,
):
    return _launch_mission_command(
        manor,
        mission,
        guest_ids,
        troop_loadout,
        seed=seed,
        scale_duration=scale_duration,
        refresh_mission_runs=refresh_mission_runs,
        import_launch_post_action_tasks=_import_launch_post_action_tasks,
        try_prepare_launch_report=_try_prepare_launch_report,
        dispatch_complete_mission_task=_dispatch_complete_mission_task,
    )


def schedule_mission_completion(run: MissionRun) -> None:
    _schedule_mission_completion_command(
        run,
        logger=logger,
        now_func=timezone.now,
        safe_apply_async=safe_apply_async,
        finalize_mission_run=finalize_mission_run,
    )


def request_retreat(run: MissionRun) -> None:
    _request_retreat_command(
        run,
        mission_run_model=MissionRun,
        schedule_mission_completion=schedule_mission_completion,
    )


def can_retreat(run: MissionRun, now=None) -> bool:
    return _can_retreat_command(run, now=now)
