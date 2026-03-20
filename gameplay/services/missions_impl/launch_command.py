from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.exceptions import (
    MissionDailyLimitError,
    MissionGuestSelectionError,
    MissionSquadSizeExceededError,
    MissionTroopLoadoutError,
)

from ...models import Manor, MissionRun, MissionTemplate
from ..battle_snapshots import build_guest_battle_snapshots
from .attempts import get_mission_daily_limit, mission_attempts_today
from .loadout import normalize_mission_loadout, travel_time_seconds


def validate_mission_attempts(manor: Manor, mission: MissionTemplate) -> None:
    attempts = mission_attempts_today(manor, mission)
    daily_limit = get_mission_daily_limit(manor, mission)
    if attempts >= daily_limit:
        raise MissionDailyLimitError()


def prepare_offense_launch_inputs(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: list[int],
    troop_loadout: dict[str, int],
) -> tuple[list[Any], dict[str, int], int]:
    from battle.services import validate_troop_capacity
    from guests.models import GuestStatus

    from ..recruitment.troops import _deduct_troops_batch

    guests = list(
        manor.guests.select_for_update().filter(id__in=guest_ids).select_related("template").prefetch_related("skills")
    )
    if len(guests) != len(set(guest_ids)):
        raise MissionGuestSelectionError("部分门客不可用或已离开庄园")
    if any(guest.status != GuestStatus.IDLE for guest in guests):
        raise MissionGuestSelectionError("部分门客不可用或已离开庄园")
    if not guests:
        raise MissionGuestSelectionError("请选择至少一名门客")

    max_squad_size = getattr(manor, "max_squad_size", None) or 0
    if max_squad_size and len(guests) > max_squad_size:
        raise MissionSquadSizeExceededError(max_squad_size)

    if mission.guest_only:
        loadout: dict[str, int] = {}
    else:
        try:
            loadout = normalize_mission_loadout(troop_loadout)
            validate_troop_capacity(guests, loadout)
        except ValueError as exc:
            raise MissionTroopLoadoutError(str(exc)) from exc

    if loadout:
        try:
            _deduct_troops_batch(manor, loadout)
        except ValueError as exc:
            raise MissionTroopLoadoutError(str(exc)) from exc

    travel_seconds = travel_time_seconds(mission.base_travel_time, guests, loadout)
    return guests, loadout, travel_seconds


def prepare_launch_inputs(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: list[int],
    troop_loadout: dict[str, int],
    *,
    scale_duration,
) -> tuple[list[Any], dict[str, int], int]:
    if mission.is_defense:
        return [], {}, scale_duration(mission.base_travel_time, minimum=1)

    return prepare_offense_launch_inputs(manor, mission, guest_ids, troop_loadout)


def mark_guests_deployed_if_needed(mission: MissionTemplate, guests: list[Any]) -> None:
    if mission.is_defense or not guests:
        return

    from guests.models import Guest, GuestStatus

    for guest in guests:
        guest.status = GuestStatus.DEPLOYED
    Guest.objects.bulk_update(guests, ["status"])


def create_mission_run_record(
    manor: Manor,
    mission: MissionTemplate,
    guests: list[Any],
    guest_snapshots: list[dict[str, Any]],
    loadout: dict[str, int],
    travel_seconds: int,
) -> MissionRun:
    return_seconds = travel_seconds if mission.is_defense else travel_seconds * 2
    run = MissionRun.objects.create(
        manor=manor,
        mission=mission,
        guest_snapshots=guest_snapshots,
        troop_loadout=loadout,
        travel_time=travel_seconds,
        return_at=timezone.now() + timedelta(seconds=return_seconds),
    )
    if not mission.is_defense:
        run.guests.set(guests)
    return run


def launch_mission(
    manor: Manor,
    mission: MissionTemplate,
    guest_ids: list[int],
    troop_loadout: dict[str, int],
    *,
    seed: Any = None,
    scale_duration,
    refresh_mission_runs,
    import_launch_post_action_tasks,
    try_prepare_launch_report,
    dispatch_complete_mission_task,
) -> MissionRun:
    refresh_mission_runs(manor)
    validate_mission_attempts(manor, mission)

    with transaction.atomic():
        Manor.objects.select_for_update().get(pk=manor.pk)
        validate_mission_attempts(manor, mission)

        guests, loadout, travel_seconds = prepare_launch_inputs(
            manor,
            mission,
            guest_ids,
            troop_loadout,
            scale_duration=scale_duration,
        )
        mark_guests_deployed_if_needed(mission, guests)
        guest_snapshots = build_guest_battle_snapshots(guests, include_identity=True)
        run = create_mission_run_record(manor, mission, guests, guest_snapshots, loadout, travel_seconds)

    generate_report_task, complete_mission_task = import_launch_post_action_tasks()
    try_prepare_launch_report(
        manor,
        mission,
        run,
        guests,
        loadout,
        travel_seconds,
        seed,
        generate_report_task,
    )
    dispatch_complete_mission_task(run, complete_mission_task)
    return run
