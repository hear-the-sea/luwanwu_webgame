from __future__ import annotations

import logging
import os
import sys
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
from .execution_adapters import (
    build_mission_drops_with_salvage_adapter,
    load_locked_mission_run,
    mark_run_completed,
    normalize_guest_configs,
    normalize_mapping,
)
from .execution_facade import finalize_mission_run_entry, launch_mission_entry
from .execution_launch_runtime import (
    dispatch_complete_mission_task_entry,
    import_launch_post_action_tasks_entry,
    schedule_mission_completion_task_entry,
    try_prepare_launch_report_entry,
)
from .execution_runtime import (
    can_retreat_entry,
    refresh_mission_runs_entry,
    request_retreat_entry,
    schedule_mission_completion_entry,
)
from .execution_runtime import try_dispatch_mission_refresh_task as runtime_try_dispatch_mission_refresh_task
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
from .launch_post_actions import (
    attach_run_report_if_empty,
    build_defender_setup_and_drop_table,
    dispatch_or_sync_launch_report,
    import_launch_post_action_tasks,
    schedule_mission_completion_task,
)
from .launch_resilience import dispatch_completion_task_best_effort, prepare_launch_report_best_effort
from .refresh_command import refresh_mission_runs as _refresh_mission_runs_command
from .refresh_command import schedule_mission_completion as _schedule_mission_completion_command
from .retreat_command import can_retreat as _can_retreat_command
from .retreat_command import request_retreat as _request_retreat_command
from .sync_report import generate_sync_battle_report

logger = logging.getLogger(__name__)


_MISSION_REFRESH_DISPATCH_DEDUP_SECONDS = 5
MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS = (ConnectionError, OSError, TimeoutError)


# Dynamic facade assembly in execution_facade.py resolves these names from this module at runtime.
_FACADE_EXPORTS = (
    scale_duration,
    guest_template_rarity_rank_case,
    apply_defender_troop_losses,
    create_message,
    notify_user,
    award_mission_drops_locked,
    apply_mission_rewards_if_won,
    build_defense_report_if_needed,
    extract_report_guest_state,
    prepare_guest_updates_for_finalize,
    return_attacker_troops_after_mission,
    select_guests_for_finalize,
    send_mission_report_message,
)


def _normalize_mapping(raw: Any) -> Dict[str, object]:
    return normalize_mapping(raw)


def _normalize_guest_configs(raw: Any) -> List[Any]:
    return normalize_guest_configs(raw)


def _try_dispatch_mission_refresh_task(task, run_id: int) -> bool:
    return runtime_try_dispatch_mission_refresh_task(
        task,
        run_id,
        safe_apply_async_with_dedup=safe_apply_async_with_dedup,
        logger=logger,
        dedup_seconds=_MISSION_REFRESH_DISPATCH_DEDUP_SECONDS,
    )


def refresh_mission_runs(manor: Manor, *, prefer_async: bool = False) -> None:
    refresh_mission_runs_entry(
        manor,
        prefer_async=prefer_async,
        refresh_mission_runs_command=_refresh_mission_runs_command,
        mission_run_model=MissionRun,
        settings_obj=settings,
        logger=logger,
        now_func=timezone.now,
        try_dispatch_mission_refresh_task=_try_dispatch_mission_refresh_task,
        finalize_mission_run=finalize_mission_run,
    )


def _load_locked_mission_run(run_pk: int) -> MissionRun | None:
    return load_locked_mission_run(mission_run_model=MissionRun, run_pk=run_pk)


def _mark_run_completed(locked_run: MissionRun, now) -> None:
    mark_run_completed(locked_run, now)


def _build_mission_drops_with_salvage(locked_run: MissionRun, report: Any, player_side: str) -> Dict[str, int]:
    return build_mission_drops_with_salvage_adapter(
        locked_run,
        report,
        player_side,
        logger=logger,
        build_mission_drops_with_salvage=build_mission_drops_with_salvage,
        resolve_defense_drops_if_missing=resolve_defense_drops_if_missing,
    )


def finalize_mission_run(run: MissionRun, now=None) -> None:
    finalize_mission_run_entry(run, now=now, service_module=sys.modules[__name__])


def _schedule_mission_completion_task(run: MissionRun, complete_mission_task) -> None:
    schedule_mission_completion_task_entry(
        run,
        complete_mission_task,
        schedule_mission_completion_task=schedule_mission_completion_task,
        safe_apply_async=safe_apply_async,
        logger=logger,
        finalize_mission_run=finalize_mission_run,
        now_func=timezone.now,
    )


def _import_launch_post_action_tasks() -> tuple[Any | None, Any | None]:
    return import_launch_post_action_tasks_entry(
        import_launch_post_action_tasks=import_launch_post_action_tasks, logger=logger
    )


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
    try_prepare_launch_report_entry(
        manor,
        mission,
        run,
        guests,
        loadout,
        travel_seconds,
        seed,
        generate_report_task,
        logger=logger,
        prepare_launch_report_best_effort=prepare_launch_report_best_effort,
        build_defender_setup_and_drop_table=build_defender_setup_and_drop_table,
        normalize_guest_configs=_normalize_guest_configs,
        normalize_mapping=_normalize_mapping,
        dispatch_or_sync_launch_report=dispatch_or_sync_launch_report,
        attach_run_report_if_empty=attach_run_report_if_empty,
        build_guest_snapshot_proxies=build_guest_snapshot_proxies,
        build_guest_battle_snapshots=build_guest_battle_snapshots,
        generate_sync_battle_report=generate_sync_battle_report,
        safe_apply_async=safe_apply_async,
        settings_obj=settings,
        environ=os.environ,
        mission_run_model=MissionRun,
    )


def _dispatch_complete_mission_task(run: MissionRun, complete_mission_task) -> None:
    dispatch_complete_mission_task_entry(
        run,
        complete_mission_task,
        dispatch_completion_task_best_effort=dispatch_completion_task_best_effort,
        logger=logger,
        schedule_mission_completion_task=_schedule_mission_completion_task,
    )


def launch_mission(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
    seed=None,
):
    return launch_mission_entry(
        manor,
        mission,
        guest_ids,
        troop_loadout,
        seed=seed,
        service_module=sys.modules[__name__],
    )


def schedule_mission_completion(run: MissionRun) -> None:
    schedule_mission_completion_entry(
        run,
        schedule_mission_completion_command=_schedule_mission_completion_command,
        logger=logger,
        now_func=timezone.now,
        safe_apply_async=safe_apply_async,
        finalize_mission_run=finalize_mission_run,
    )


def request_retreat(run: MissionRun) -> None:
    request_retreat_entry(
        run,
        request_retreat_command=_request_retreat_command,
        mission_run_model=MissionRun,
        schedule_mission_completion=schedule_mission_completion,
    )


def can_retreat(run: MissionRun, now=None) -> bool:
    return can_retreat_entry(run, can_retreat_command=_can_retreat_command, now=now)
