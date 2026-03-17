from __future__ import annotations

from typing import Any, Callable


def build_start_raid_dependencies(
    *,
    validate_and_normalize_inputs: Callable[..., Any],
    transaction_atomic: Callable[..., Any],
    lock_manor_pair: Callable[..., Any],
    now_func: Callable[..., Any],
    recheck_can_attack_target: Callable[..., Any],
    get_active_raid_count: Callable[..., Any],
    raid_max_concurrent: int,
    load_and_validate_attacker_guests: Callable[..., Any],
    normalize_and_validate_raid_loadout: Callable[..., Any],
    deduct_troops: Callable[..., Any],
    calculate_raid_travel_time: Callable[..., Any],
    create_raid_run_record: Callable[..., Any],
    invalidate_recent_attacks_cache_on_commit: Callable[..., Any],
    send_raid_incoming_message: Callable[..., Any],
    dispatch_raid_battle_task: Callable[..., Any],
    logger: Any,
) -> dict[str, Any]:
    return {
        "validate_and_normalize_inputs": validate_and_normalize_inputs,
        "transaction_atomic": transaction_atomic,
        "lock_manor_pair": lock_manor_pair,
        "now_func": now_func,
        "recheck_can_attack_target": recheck_can_attack_target,
        "get_active_raid_count": get_active_raid_count,
        "raid_max_concurrent": raid_max_concurrent,
        "load_and_validate_attacker_guests": load_and_validate_attacker_guests,
        "normalize_and_validate_raid_loadout": normalize_and_validate_raid_loadout,
        "deduct_troops": deduct_troops,
        "calculate_raid_travel_time": calculate_raid_travel_time,
        "create_raid_run_record": create_raid_run_record,
        "invalidate_recent_attacks_cache_on_commit": invalidate_recent_attacks_cache_on_commit,
        "send_raid_incoming_message": send_raid_incoming_message,
        "dispatch_raid_battle_task": dispatch_raid_battle_task,
        "logger": logger,
    }


def build_finalize_raid_dependencies(
    *,
    load_locked_raid_run: Callable[..., Any],
    normalize_positive_int_mapping: Callable[..., Any],
    return_surviving_troops: Callable[..., Any],
    load_locked_attacker: Callable[..., Any],
    grant_resources_locked: Callable[..., Any],
    grant_loot_items: Callable[..., Any],
    battle_reward_reason: Any,
) -> dict[str, Any]:
    return {
        "load_locked_raid_run": load_locked_raid_run,
        "normalize_positive_int_mapping": normalize_positive_int_mapping,
        "return_surviving_troops": return_surviving_troops,
        "load_locked_attacker": load_locked_attacker,
        "grant_resources_locked": grant_resources_locked,
        "grant_loot_items": grant_loot_items,
        "battle_reward_reason": battle_reward_reason,
    }


def build_refresh_raid_dependencies(
    *,
    now_func: Callable[..., Any],
    raid_run_model: Any,
    collect_due_raid_run_ids: Callable[..., Any],
    dispatch_async_raid_refresh: Callable[..., Any],
    logger: Any,
    import_raid_refresh_tasks: Callable[..., Any],
    try_dispatch_raid_refresh_task: Callable[..., Any],
    process_due_raid_run_ids: Callable[..., Any],
    process_raid_battle: Callable[..., Any],
    finalize_raid: Callable[..., Any],
) -> dict[str, Any]:
    return {
        "now_func": now_func,
        "raid_run_model": raid_run_model,
        "collect_due_raid_run_ids": collect_due_raid_run_ids,
        "dispatch_async_raid_refresh": dispatch_async_raid_refresh,
        "logger": logger,
        "import_raid_refresh_tasks": import_raid_refresh_tasks,
        "try_dispatch_raid_refresh_task": try_dispatch_raid_refresh_task,
        "process_due_raid_run_ids": process_due_raid_run_ids,
        "process_raid_battle": process_raid_battle,
        "finalize_raid": finalize_raid,
    }
