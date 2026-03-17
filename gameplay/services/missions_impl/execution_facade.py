from __future__ import annotations

from typing import Any

from .execution_wiring import build_finalize_mission_dependencies, build_launch_mission_dependencies
from .finalize_command import finalize_mission_run as _finalize_mission_run_command
from .launch_command import launch_mission as _launch_mission_command


def finalize_mission_run_entry(run: Any, *, now: Any = None, service_module: Any) -> None:
    _finalize_mission_run_command(
        run,
        now=now,
        **build_finalize_mission_dependencies(
            load_locked_mission_run=getattr(service_module, "_load_locked_mission_run"),
            build_defense_report_if_needed=getattr(service_module, "build_defense_report_if_needed"),
            guest_template_rarity_rank_case=getattr(service_module, "guest_template_rarity_rank_case"),
            generate_sync_battle_report=getattr(service_module, "generate_sync_battle_report"),
            extract_report_guest_state=getattr(service_module, "extract_report_guest_state"),
            select_guests_for_finalize=getattr(service_module, "select_guests_for_finalize"),
            prepare_guest_updates_for_finalize=getattr(service_module, "prepare_guest_updates_for_finalize"),
            mark_run_completed=getattr(service_module, "_mark_run_completed"),
            apply_defender_troop_losses=getattr(service_module, "apply_defender_troop_losses"),
            return_attacker_troops_after_mission=getattr(service_module, "return_attacker_troops_after_mission"),
            logger=getattr(service_module, "logger"),
            apply_mission_rewards_if_won=getattr(service_module, "apply_mission_rewards_if_won"),
            resolve_defense_drops_if_missing=getattr(service_module, "resolve_defense_drops_if_missing"),
            award_mission_drops_locked=getattr(service_module, "award_mission_drops_locked"),
            send_mission_report_message=getattr(service_module, "send_mission_report_message"),
            create_message=getattr(service_module, "create_message"),
            notify_user=getattr(service_module, "notify_user"),
            notification_infrastructure_exceptions=getattr(
                service_module, "MISSION_NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS"
            ),
        ),
    )


def launch_mission_entry(
    manor: Any,
    mission: Any,
    guest_ids: list[int],
    troop_loadout: dict[str, int],
    *,
    seed: Any = None,
    service_module: Any,
):
    return _launch_mission_command(
        manor,
        mission,
        guest_ids,
        troop_loadout,
        seed=seed,
        **build_launch_mission_dependencies(
            scale_duration=getattr(service_module, "scale_duration"),
            refresh_mission_runs=getattr(service_module, "refresh_mission_runs"),
            import_launch_post_action_tasks=getattr(service_module, "_import_launch_post_action_tasks"),
            try_prepare_launch_report=getattr(service_module, "_try_prepare_launch_report"),
            dispatch_complete_mission_task=getattr(service_module, "_dispatch_complete_mission_task"),
        ),
    )
