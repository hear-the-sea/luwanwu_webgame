from __future__ import annotations

from typing import Any

from .finalize import finalize_raid as _finalize_raid_command
from .refresh import refresh_raid_runs as _refresh_raid_runs_command
from .run_wiring import build_finalize_raid_dependencies, build_refresh_raid_dependencies, build_start_raid_dependencies
from .start import start_raid as _start_raid_command


def start_raid_entry(
    attacker: Any,
    defender: Any,
    guest_ids: list[int],
    troop_loadout: dict[str, int],
    *,
    service_module: Any,
) -> Any:
    return _start_raid_command(
        attacker,
        defender,
        guest_ids,
        troop_loadout,
        **build_start_raid_dependencies(
            validate_and_normalize_inputs=getattr(service_module, "_validate_and_normalize_raid_inputs"),
            transaction_atomic=getattr(service_module, "transaction").atomic,
            lock_manor_pair=getattr(service_module, "_lock_manor_pair"),
            now_func=getattr(service_module, "timezone").now,
            recheck_can_attack_target=getattr(service_module, "_recheck_can_attack_target"),
            get_active_raid_count=getattr(service_module, "get_active_raid_count"),
            raid_max_concurrent=getattr(service_module, "PVPConstants").RAID_MAX_CONCURRENT,
            load_and_validate_attacker_guests=getattr(service_module, "_load_and_validate_attacker_guests"),
            normalize_and_validate_raid_loadout=getattr(service_module, "_normalize_and_validate_raid_loadout"),
            deduct_troops=getattr(service_module, "_deduct_troops"),
            calculate_raid_travel_time=getattr(service_module, "calculate_raid_travel_time"),
            create_raid_run_record=getattr(service_module, "_create_raid_run_record"),
            invalidate_recent_attacks_cache_on_commit=getattr(
                service_module, "_invalidate_recent_attacks_cache_on_commit"
            ),
            send_raid_incoming_message=getattr(service_module, "_send_raid_incoming_message"),
            dispatch_raid_battle_task=getattr(service_module, "_dispatch_raid_battle_task"),
            logger=getattr(service_module, "logger"),
        ),
    )


def finalize_raid_entry(run: Any, *, now: Any = None, service_module: Any) -> None:
    grant_resources_locked = __import__(
        "gameplay.services.resources",
        fromlist=["grant_resources_locked"],
    ).grant_resources_locked

    _finalize_raid_command(
        run,
        now=now,
        **build_finalize_raid_dependencies(
            load_locked_raid_run=getattr(service_module, "_load_locked_raid_run"),
            normalize_positive_int_mapping=getattr(service_module, "_normalize_positive_int_mapping"),
            return_surviving_troops=getattr(service_module, "_return_surviving_troops"),
            load_locked_attacker=getattr(service_module, "_load_locked_attacker"),
            grant_resources_locked=grant_resources_locked,
            grant_loot_items=getattr(service_module, "_grant_loot_items"),
            battle_reward_reason=getattr(service_module, "ResourceEvent").Reason.BATTLE_REWARD,
        ),
    )


def refresh_raid_runs_entry(manor: Any, *, prefer_async: bool, service_module: Any) -> None:
    process_raid_battle = __import__(
        "gameplay.services.raid.combat.battle",
        fromlist=["process_raid_battle"],
    ).process_raid_battle

    _refresh_raid_runs_command(
        manor,
        prefer_async=prefer_async,
        **build_refresh_raid_dependencies(
            now_func=getattr(service_module, "timezone").now,
            raid_run_model=getattr(service_module, "RaidRun"),
            collect_due_raid_run_ids=getattr(service_module, "collect_due_raid_run_ids"),
            dispatch_async_raid_refresh=getattr(service_module, "dispatch_async_raid_refresh"),
            logger=getattr(service_module, "logger"),
            import_raid_refresh_tasks=getattr(service_module, "_import_raid_refresh_tasks"),
            try_dispatch_raid_refresh_task=getattr(service_module, "_try_dispatch_raid_refresh_task"),
            process_due_raid_run_ids=getattr(service_module, "process_due_raid_run_ids"),
            process_raid_battle=process_raid_battle,
            finalize_raid=getattr(service_module, "finalize_raid"),
        ),
    )
