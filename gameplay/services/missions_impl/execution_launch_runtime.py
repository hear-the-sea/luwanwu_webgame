from __future__ import annotations

from typing import Any, Dict, List, Mapping


def schedule_mission_completion_task_entry(
    run: Any,
    complete_mission_task: Any,
    *,
    schedule_mission_completion_task,
    safe_apply_async,
    logger: Any,
    finalize_mission_run,
    now_func,
) -> None:
    schedule_mission_completion_task(
        run,
        complete_mission_task,
        safe_apply_async=safe_apply_async,
        logger=logger,
        finalize_mission_run=finalize_mission_run,
        now_func=now_func,
    )


def import_launch_post_action_tasks_entry(
    *, import_launch_post_action_tasks, logger: Any
) -> tuple[Any | None, Any | None]:
    return import_launch_post_action_tasks(logger=logger)


def try_prepare_launch_report_entry(
    manor: Any,
    mission: Any,
    run: Any,
    guests: List[Any],
    loadout: Dict[str, int],
    travel_seconds: int,
    seed: Any,
    generate_report_task: Any,
    *,
    logger: Any,
    prepare_launch_report_best_effort,
    build_defender_setup_and_drop_table,
    normalize_guest_configs,
    normalize_mapping,
    dispatch_or_sync_launch_report,
    attach_run_report_if_empty,
    build_guest_snapshot_proxies,
    build_guest_battle_snapshots,
    generate_sync_battle_report,
    safe_apply_async,
    settings_obj: Any,
    environ: Mapping[str, str],
    mission_run_model: Any,
) -> None:
    prepare_launch_report_best_effort(
        manor,
        mission,
        run,
        guests,
        loadout,
        travel_seconds,
        seed,
        generate_report_task,
        logger=logger,
        build_defender_setup_and_drop_table=build_defender_setup_and_drop_table,
        normalize_guest_configs=normalize_guest_configs,
        normalize_mapping=normalize_mapping,
        dispatch_or_sync_launch_report=dispatch_or_sync_launch_report,
        attach_run_report_if_empty=attach_run_report_if_empty,
        build_guest_snapshot_proxies=build_guest_snapshot_proxies,
        build_guest_battle_snapshots=build_guest_battle_snapshots,
        generate_sync_battle_report=generate_sync_battle_report,
        safe_apply_async=safe_apply_async,
        settings_obj=settings_obj,
        environ=environ,
        mission_run_model=mission_run_model,
    )


def dispatch_complete_mission_task_entry(
    run: Any,
    complete_mission_task: Any,
    *,
    dispatch_completion_task_best_effort,
    logger: Any,
    schedule_mission_completion_task,
) -> None:
    dispatch_completion_task_best_effort(
        run,
        complete_mission_task,
        logger=logger,
        schedule_mission_completion_task=schedule_mission_completion_task,
    )
