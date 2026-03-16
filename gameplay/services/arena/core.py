from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from core.utils.cache_lock import acquire_best_effort_lock, release_best_effort_lock
from gameplay.models import ArenaEntry, ArenaEntryGuest, ArenaMatch, ArenaTournament, Manor
from guests.models import Guest, GuestStatus
from guests.services.loyalty import increase_guest_loyalty_by_ids

from . import helpers as _arena_helpers
from .exchange_helpers import ArenaExchangeResult, exchange_arena_reward  # noqa: F401
from .lifecycle_helpers import cleanup_expired_tournaments as _cleanup_expired_tournaments
from .lifecycle_helpers import finalize_tournament_locked as _finalize_tournament_locked_impl
from .lifecycle_helpers import schedule_round_locked as _schedule_round_locked_impl
from .match_helpers import resolve_match_locked as _resolve_match_locked_impl
from .match_helpers import save_resolved_match as _save_resolved_match_impl
from .registration_helpers import (
    collect_cancelable_recruiting_entries_locked,
    create_arena_entry_with_guests_locked,
    deduct_registration_silver_locked,
    load_selected_registration_guests_locked,
)
from .round_helpers import finalize_round_state_locked as _finalize_round_state_locked_impl
from .round_helpers import load_round_entries_for_matches as _load_round_entries_for_matches_impl
from .round_helpers import resolve_pending_round_matches as _resolve_pending_round_matches_impl
from .rules import load_arena_rules
from .snapshots import build_entry_guest_snapshot
from .state_helpers import sync_daily_participation_counter_locked as _sync_daily_participation_counter_locked
from .state_helpers import update_daily_participation_counter_locked as _update_daily_participation_counter_locked

logger = logging.getLogger(__name__)


_load_positive_int_setting = _arena_helpers.load_positive_int_setting


ARENA_RULES = load_arena_rules()
ARENA_DAILY_PARTICIPATION_LIMIT = _load_positive_int_setting(
    "ARENA_DAILY_PARTICIPATION_LIMIT", ARENA_RULES["registration"]["daily_participation_limit"], minimum=1
)
ARENA_MAX_GUESTS_PER_ENTRY = int(ARENA_RULES["registration"]["max_guests_per_entry"])
ARENA_TOURNAMENT_PLAYER_LIMIT = _load_positive_int_setting(
    "ARENA_TOURNAMENT_PLAYER_LIMIT", ARENA_RULES["registration"]["tournament_player_limit"], minimum=2
)
ARENA_ROUND_INTERVAL_SECONDS = int(ARENA_RULES["runtime"]["round_interval_seconds"])
ARENA_COMPLETED_RETENTION_SECONDS = int(ARENA_RULES["runtime"]["completed_retention_seconds"])
ARENA_ROUND_RETRY_SECONDS = int(ARENA_RULES["runtime"]["round_retry_seconds"])
ARENA_REGISTRATION_SILVER_COST = int(ARENA_RULES["registration"]["registration_silver_cost"])
ARENA_BASE_PARTICIPATION_COINS = int(ARENA_RULES["rewards"]["base_participation_coins"])
ARENA_RANK_BONUS_COINS = dict(ARENA_RULES["rewards"]["rank_bonus_coins"])
ARENA_RECRUITING_LOCK_KEY = str(ARENA_RULES["runtime"]["recruiting_lock_key"])
ARENA_RECRUITING_LOCK_TIMEOUT = int(ARENA_RULES["runtime"]["recruiting_lock_timeout"])


def refresh_arena_constants() -> None:
    """重新从 YAML 加载竞技场规则并更新模块级常量。"""
    global ARENA_RULES
    global ARENA_DAILY_PARTICIPATION_LIMIT, ARENA_MAX_GUESTS_PER_ENTRY, ARENA_TOURNAMENT_PLAYER_LIMIT
    global ARENA_ROUND_INTERVAL_SECONDS, ARENA_COMPLETED_RETENTION_SECONDS, ARENA_ROUND_RETRY_SECONDS
    global ARENA_REGISTRATION_SILVER_COST, ARENA_BASE_PARTICIPATION_COINS, ARENA_RANK_BONUS_COINS
    global ARENA_RECRUITING_LOCK_KEY, ARENA_RECRUITING_LOCK_TIMEOUT

    ARENA_RULES = load_arena_rules()
    ARENA_DAILY_PARTICIPATION_LIMIT = _load_positive_int_setting(
        "ARENA_DAILY_PARTICIPATION_LIMIT", ARENA_RULES["registration"]["daily_participation_limit"], minimum=1
    )
    ARENA_MAX_GUESTS_PER_ENTRY = int(ARENA_RULES["registration"]["max_guests_per_entry"])
    ARENA_TOURNAMENT_PLAYER_LIMIT = _load_positive_int_setting(
        "ARENA_TOURNAMENT_PLAYER_LIMIT", ARENA_RULES["registration"]["tournament_player_limit"], minimum=2
    )
    ARENA_ROUND_INTERVAL_SECONDS = int(ARENA_RULES["runtime"]["round_interval_seconds"])
    ARENA_COMPLETED_RETENTION_SECONDS = int(ARENA_RULES["runtime"]["completed_retention_seconds"])
    ARENA_ROUND_RETRY_SECONDS = int(ARENA_RULES["runtime"]["round_retry_seconds"])
    ARENA_REGISTRATION_SILVER_COST = int(ARENA_RULES["registration"]["registration_silver_cost"])
    ARENA_BASE_PARTICIPATION_COINS = int(ARENA_RULES["rewards"]["base_participation_coins"])
    ARENA_RANK_BONUS_COINS = dict(ARENA_RULES["rewards"]["rank_bonus_coins"])
    ARENA_RECRUITING_LOCK_KEY = str(ARENA_RULES["runtime"]["recruiting_lock_key"])
    ARENA_RECRUITING_LOCK_TIMEOUT = int(ARENA_RULES["runtime"]["recruiting_lock_timeout"])


@dataclass(frozen=True)
class ArenaRegistrationResult:
    entry: ArenaEntry
    tournament: ArenaTournament
    auto_started: bool
    entry_count: int


class ArenaMatchResolutionError(RuntimeError):
    """Raised when a round match cannot be resolved and should be retried."""


def _normalize_guest_ids(guest_ids: Iterable[int]) -> list[int]:
    return _arena_helpers.normalize_guest_ids(guest_ids, max_guests_per_entry=ARENA_MAX_GUESTS_PER_ENTRY)


def _round_interval_seconds() -> int:
    return _arena_helpers.round_interval_seconds(ARENA_ROUND_INTERVAL_SECONDS)


_load_round_entries_for_matches = _load_round_entries_for_matches_impl
_resolve_pending_round_matches = _resolve_pending_round_matches_impl


_build_entry_guest_snapshot = build_entry_guest_snapshot


def _get_or_create_recruiting_tournament_locked() -> ArenaTournament:
    tournament = (
        ArenaTournament.objects.select_for_update()
        .filter(status=ArenaTournament.Status.RECRUITING)
        .annotate(entry_count=Count("entries"))
        .filter(entry_count__lt=F("player_limit"))
        .order_by("created_at")
        .first()
    )
    if tournament:
        return tournament

    acquired, from_cache, lock_token = acquire_best_effort_lock(
        ARENA_RECRUITING_LOCK_KEY,
        timeout_seconds=ARENA_RECRUITING_LOCK_TIMEOUT,
        logger=logger,
        log_context="arena recruiting tournament lock",
        allow_local_fallback=False,
    )
    if not acquired:
        existing = (
            ArenaTournament.objects.filter(status=ArenaTournament.Status.RECRUITING)
            .annotate(entry_count=Count("entries"))
            .filter(entry_count__lt=F("player_limit"))
            .order_by("created_at")
            .first()
        )
        if existing:
            return existing
        raise ValueError("竞技场报名繁忙，请稍后重试")

    try:
        existing = (
            ArenaTournament.objects.select_for_update()
            .filter(status=ArenaTournament.Status.RECRUITING)
            .annotate(entry_count=Count("entries"))
            .filter(entry_count__lt=F("player_limit"))
            .order_by("created_at")
            .first()
        )
        if existing:
            return existing

        return ArenaTournament.objects.create(
            status=ArenaTournament.Status.RECRUITING,
            player_limit=ARENA_TOURNAMENT_PLAYER_LIMIT,
            round_interval_seconds=_round_interval_seconds(),
        )
    finally:
        release_best_effort_lock(
            ARENA_RECRUITING_LOCK_KEY,
            from_cache=from_cache,
            lock_token=lock_token,
            logger=logger,
            log_context="arena recruiting tournament lock",
        )


def _start_tournament_locked(tournament: ArenaTournament, *, now: datetime | None = None) -> bool:
    if tournament.status != ArenaTournament.Status.RECRUITING:
        return False
    entry_count = tournament.entries.count()
    if entry_count < tournament.player_limit:
        return False

    current_time = now or timezone.now()
    tournament.status = ArenaTournament.Status.RUNNING
    tournament.started_at = current_time
    tournament.current_round = 0
    tournament.save(update_fields=["status", "started_at", "current_round", "updated_at"])
    _schedule_round_locked(tournament, round_number=1, now=current_time)
    return True


def _round_interval_delta(tournament: ArenaTournament) -> timedelta:
    return _arena_helpers.round_interval_delta(tournament.round_interval_seconds)


_build_round_pairings = _arena_helpers.build_round_pairings


def _schedule_round_locked(tournament: ArenaTournament, *, round_number: int, now: datetime) -> bool:
    return _schedule_round_locked_impl(
        tournament,
        round_number=round_number,
        now=now,
        build_round_pairings=_build_round_pairings,
        round_interval_delta=_round_interval_delta,
        finalize_tournament_locked=_finalize_tournament_locked,
    )


@transaction.atomic
def register_arena_entry(manor: Manor, guest_ids: Iterable[int]) -> ArenaRegistrationResult:
    selected_guest_ids = _normalize_guest_ids(guest_ids)
    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)

    if _sync_daily_participation_counter_locked(locked_manor) >= ARENA_DAILY_PARTICIPATION_LIMIT:
        raise ValueError(f"每日最多参加 {ARENA_DAILY_PARTICIPATION_LIMIT} 次竞技场")

    if ArenaEntry.objects.filter(
        manor=locked_manor,
        tournament__status__in=[ArenaTournament.Status.RECRUITING, ArenaTournament.Status.RUNNING],
    ).exists():
        raise ValueError("您已有进行中的竞技场报名，请等待本场结束")

    selected_guests = load_selected_registration_guests_locked(locked_manor, selected_guest_ids)
    deduct_registration_silver_locked(locked_manor, silver_cost=ARENA_REGISTRATION_SILVER_COST)
    tournament = _get_or_create_recruiting_tournament_locked()
    entry = create_arena_entry_with_guests_locked(
        tournament=tournament,
        locked_manor=locked_manor,
        selected_guests=selected_guests,
        build_entry_guest_snapshot=_build_entry_guest_snapshot,
    )

    entry_count = tournament.entries.count()
    auto_started = False
    if entry_count >= tournament.player_limit:
        auto_started = _start_tournament_locked(tournament)
    _update_daily_participation_counter_locked(locked_manor, delta=1)

    return ArenaRegistrationResult(
        entry=entry,
        tournament=tournament,
        auto_started=auto_started,
        entry_count=entry_count,
    )


@transaction.atomic
def cancel_arena_entry(manor: Manor) -> int:
    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
    recruiting_entries, participant_guest_ids = collect_cancelable_recruiting_entries_locked(locked_manor)

    entry_ids = [entry.id for entry in recruiting_entries]
    ArenaEntry.objects.filter(id__in=entry_ids).delete()
    if participant_guest_ids:
        Guest.objects.filter(id__in=participant_guest_ids, status=GuestStatus.DEPLOYED).update(status=GuestStatus.IDLE)

    _update_daily_participation_counter_locked(locked_manor, delta=-len(entry_ids))
    return len(entry_ids)


@transaction.atomic
def start_tournament_if_ready(tournament: ArenaTournament, *, now: datetime | None = None) -> bool:
    locked = ArenaTournament.objects.select_for_update().filter(pk=tournament.pk).first()
    if not locked:
        return False
    return _start_tournament_locked(locked, now=now)


def start_ready_tournaments(limit: int = 20) -> int:
    candidate_ids = list(
        ArenaTournament.objects.filter(status=ArenaTournament.Status.RECRUITING)
        .annotate(entry_count=Count("entries"))
        .filter(entry_count__gte=F("player_limit"))
        .order_by("created_at")
        .values_list("id", flat=True)[: max(1, int(limit))]
    )
    started_count = 0
    for tournament_id in candidate_ids:
        try:
            if start_tournament_if_ready(ArenaTournament(id=tournament_id)):
                started_count += 1
        except Exception:
            logger.exception("failed to start ready tournament: tournament_id=%s", tournament_id)
    return started_count


def _resolve_match_locked(
    *,
    tournament: ArenaTournament,
    round_number: int,
    match_index: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    now: datetime,
    match: ArenaMatch | None = None,
) -> ArenaEntry:
    return _resolve_match_locked_impl(
        tournament=tournament,
        round_number=round_number,
        match_index=match_index,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        now=now,
        max_guests_per_entry=ARENA_MAX_GUESTS_PER_ENTRY,
        arena_match_resolution_error=ArenaMatchResolutionError,
        match=match,
        logger=logger,
    )


_calculate_ranked_entries = _arena_helpers.calculate_ranked_entries


def _reward_for_rank(rank: int) -> int:
    return _arena_helpers.reward_for_rank(
        rank,
        base_participation_coins=ARENA_BASE_PARTICIPATION_COINS,
        rank_bonus_coins=ARENA_RANK_BONUS_COINS,
    )


def _finalize_tournament_locked(tournament: ArenaTournament, *, winner_entry: ArenaEntry | None, now: datetime) -> None:
    _finalize_tournament_locked_impl(
        tournament,
        winner_entry=winner_entry,
        now=now,
        calculate_ranked_entries=_calculate_ranked_entries,
        reward_for_rank=_reward_for_rank,
        logger=logger,
    )


def _schedule_round_retry_locked(tournament: ArenaTournament, *, now: datetime) -> None:
    retry_seconds = max(1, min(ARENA_ROUND_RETRY_SECONDS, _round_interval_seconds()))
    tournament.next_round_at = now + timedelta(seconds=retry_seconds)
    tournament.save(update_fields=["next_round_at", "updated_at"])


_collect_round_outcome_entry_ids = _arena_helpers.collect_round_outcome_entry_ids


def _run_tournament_round(tournament_id: int, *, now: datetime) -> bool:
    with transaction.atomic():
        tournament = ArenaTournament.objects.select_for_update().filter(pk=tournament_id).first()
        if not tournament:
            return False
        if tournament.status != ArenaTournament.Status.RUNNING:
            return False
        if not tournament.next_round_at or tournament.next_round_at > now:
            return False
        pending_matches = list(
            ArenaMatch.objects.select_for_update()
            .filter(
                tournament=tournament,
                round_number=tournament.current_round,
                status=ArenaMatch.Status.SCHEDULED,
            )
            .order_by("match_index", "id")
        )

        if not pending_matches:
            next_round_number = max(1, tournament.current_round + 1)
            return _schedule_round_locked(tournament, round_number=next_round_number, now=now)

        round_number = tournament.current_round
        pending_match_ids = [match.id for match in pending_matches]
        # 避免并发 worker 重复处理本轮，先把下次扫描时间推后。
        tournament.next_round_at = now + _round_interval_delta(tournament)
        tournament.save(update_fields=["next_round_at", "updated_at"])

    pending_matches, entry_map = _load_round_entries_for_matches(
        arena_match_model=ArenaMatch,
        arena_entry_model=ArenaEntry,
        pending_match_ids=pending_match_ids,
    )
    resolution_failed = _resolve_pending_round_matches(
        pending_matches=pending_matches,
        entry_map=entry_map,
        round_number=round_number,
        now=now,
        bye_status=ArenaMatch.Status.BYE,
        forfeit_status=ArenaMatch.Status.FORFEIT,
        save_resolved_match=_save_resolved_match_impl,
        resolve_match_locked=_resolve_match_locked,
        arena_match_resolution_error=ArenaMatchResolutionError,
    )

    with transaction.atomic():
        return _finalize_round_state_locked_impl(
            arena_tournament_model=ArenaTournament,
            arena_match_model=ArenaMatch,
            arena_entry_model=ArenaEntry,
            arena_entry_guest_model=ArenaEntryGuest,
            tournament_id=tournament_id,
            round_number=round_number,
            now=now,
            running_status=ArenaTournament.Status.RUNNING,
            scheduled_status=ArenaMatch.Status.SCHEDULED,
            registered_status=ArenaEntry.Status.REGISTERED,
            eliminated_status=ArenaEntry.Status.ELIMINATED,
            resolution_failed=resolution_failed,
            collect_round_outcome_entry_ids=_collect_round_outcome_entry_ids,
            schedule_round_retry_locked=_schedule_round_retry_locked,
            finalize_tournament_locked=_finalize_tournament_locked,
            schedule_round_locked=_schedule_round_locked,
            increase_guest_loyalty_by_ids=increase_guest_loyalty_by_ids,
        )


def run_due_arena_rounds(*, now: datetime | None = None, limit: int = 20) -> int:
    current_time = now or timezone.now()
    due_ids = list(
        ArenaTournament.objects.filter(
            status=ArenaTournament.Status.RUNNING,
            next_round_at__isnull=False,
            next_round_at__lte=current_time,
        )
        .order_by("next_round_at")
        .values_list("id", flat=True)[: max(1, int(limit))]
    )

    processed = 0
    for tournament_id in due_ids:
        try:
            if _run_tournament_round(tournament_id, now=current_time):
                processed += 1
        except Exception:
            logger.exception("failed to process arena round: tournament_id=%s", tournament_id)
    return processed


def cleanup_expired_tournaments(
    *, now: datetime | None = None, grace_seconds: int = ARENA_COMPLETED_RETENTION_SECONDS, limit: int = 50
) -> int:
    current_time = now or timezone.now()
    return _cleanup_expired_tournaments(now=current_time, grace_seconds=grace_seconds, limit=limit)


# exchange_arena_reward 及 ArenaExchangeResult 已移至 exchange_helpers，通过顶部 import 重新导出。
