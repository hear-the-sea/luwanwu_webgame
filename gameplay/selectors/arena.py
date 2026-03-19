from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.db.models import Count, Q
from django.utils import timezone

from common.constants.resources import ResourceType
from core.utils.time_scale import scale_duration
from gameplay.models import ArenaEntry, ArenaExchangeRecord, ArenaMatch, ArenaTournament, Manor
from gameplay.services.arena import core as arena_core
from gameplay.services.arena.rewards import load_arena_reward_catalog
from gameplay.utils.template_loader import get_item_template_names_by_keys
from guests.models import GuestStatus

ARENA_PRIMARY_EVENT_BASE = {
    "key": "tianxia_buwu",
    "name": "天下布武",
    "description": "报名满员后自动开赛，每 10 分钟推进一轮，直到决出最终胜者。",
}


def _build_reward_rows(manor: Manor) -> list[dict]:
    catalog = load_arena_reward_catalog()
    resource_labels = dict(ResourceType.choices)
    all_item_keys: set[str] = set()
    for reward in catalog.values():
        all_item_keys.update(reward.items.keys())
        all_item_keys.update(option.item_key for option in reward.random_items)
    item_labels = get_item_template_names_by_keys(all_item_keys)
    rows: list[dict] = []
    for reward in catalog.values():
        resource_rows = [
            {
                "key": key,
                "label": resource_labels.get(key, key),
                "amount": amount,
            }
            for key, amount in reward.resources.items()
        ]
        item_rows = [
            {
                "key": key,
                "label": item_labels.get(key, key),
                "amount": amount,
            }
            for key, amount in reward.items.items()
        ]
        total_random_weight = sum(option.weight for option in reward.random_items)
        random_item_rows = []
        for option in reward.random_items:
            chance = (option.weight * 100 / total_random_weight) if total_random_weight > 0 else 0
            chance_float = float(chance)
            chance_text = f"{int(chance_float)}%" if chance_float.is_integer() else f"{chance_float:.2f}%"
            random_item_rows.append(
                {
                    "key": option.item_key,
                    "label": item_labels.get(option.item_key, option.item_key),
                    "amount": option.amount,
                    "weight": option.weight,
                    "chance_text": chance_text,
                }
            )
        rows.append(
            {
                "key": reward.key,
                "name": reward.name,
                "description": reward.description,
                "cost_coins": reward.cost_coins,
                "daily_limit": reward.daily_limit,
                "resources": reward.resources,
                "items": reward.items,
                "resource_rows": resource_rows,
                "item_rows": item_rows,
                "random_item_rows": random_item_rows,
                "can_afford": manor.arena_coins >= reward.cost_coins,
            }
        )
    rows.sort(key=lambda item: (item["cost_coins"], item["key"]))
    return rows


def _running_row_sort_key(row: dict[str, Any]) -> tuple[int, Any, int]:
    tournament = cast(ArenaTournament, row["tournament"])
    return (
        0 if row["is_mine"] else 1,
        tournament.next_round_at or timezone.now(),
        tournament.id,
    )


def _today_participation_stats(manor: Manor) -> tuple[int, int]:
    today = timezone.localdate()
    if manor.arena_participation_date == today:
        today_participations = max(0, int(manor.arena_participations_today or 0))
    else:
        # 兼容旧数据：当天首次访问且计数字段尚未写入时，回退到当日报名记录统计。
        current_time = timezone.localtime(timezone.now())
        day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        today_participations = ArenaEntry.objects.filter(
            manor=manor,
            joined_at__gte=day_start,
            joined_at__lt=day_end,
        ).count()
    remaining_daily = max(0, arena_core.ARENA_DAILY_PARTICIPATION_LIMIT - today_participations)
    return today_participations, remaining_daily


def _get_active_entry(manor: Manor) -> ArenaEntry | None:
    return (
        ArenaEntry.objects.select_related("tournament")
        .prefetch_related("entry_guests__guest")
        .filter(manor=manor, tournament__status__in=[ArenaTournament.Status.RECRUITING, ArenaTournament.Status.RUNNING])
        .order_by("-joined_at")
        .first()
    )


def _build_common_context(manor: Manor) -> dict:
    today_participations, remaining_daily = _today_participation_stats(manor)
    round_interval_seconds = max(1, scale_duration(arena_core.ARENA_ROUND_INTERVAL_SECONDS, minimum=1))
    if round_interval_seconds % 60 == 0:
        round_interval_label = f"{round_interval_seconds // 60} 分钟"
    else:
        round_interval_label = f"{round_interval_seconds} 秒"

    return {
        "manor": manor,
        "today_participations": today_participations,
        "remaining_daily": remaining_daily,
        "daily_limit": arena_core.ARENA_DAILY_PARTICIPATION_LIMIT,
        "max_guests_per_entry": arena_core.ARENA_MAX_GUESTS_PER_ENTRY,
        "arena_event": {
            **ARENA_PRIMARY_EVENT_BASE,
            "subtitle": f"{arena_core.ARENA_TOURNAMENT_PLAYER_LIMIT} 人门客淘汰赛",
            "player_limit": arena_core.ARENA_TOURNAMENT_PLAYER_LIMIT,
            "round_interval_seconds": round_interval_seconds,
            "round_interval_label": round_interval_label,
        },
        "registration_silver_cost": arena_core.ARENA_REGISTRATION_SILVER_COST,
        "can_afford_registration": manor.silver >= arena_core.ARENA_REGISTRATION_SILVER_COST,
    }


def get_arena_registration_context(manor: Manor) -> dict:
    context = _build_common_context(manor)
    active_entry = _get_active_entry(manor)

    context["active_entry"] = active_entry
    context["recruiting_tournament"] = (
        ArenaTournament.objects.filter(status=ArenaTournament.Status.RECRUITING)
        .annotate(entry_count=Count("entries"))
        .order_by("created_at")
        .first()
    )
    selected_guest_ids: set[int] = set()
    available_guests = manor.guests.none()

    if active_entry:
        selected_guest_ids = set(active_entry.entry_guests.values_list("guest_id", flat=True))
    elif context["remaining_daily"] > 0:
        available_guests = (
            manor.guests.select_related("template").filter(status=GuestStatus.IDLE).order_by("-level", "id")
        )

    context["available_guests"] = available_guests
    context["selected_guest_ids"] = selected_guest_ids
    return context


def get_arena_events_context(manor: Manor) -> dict:
    context = _build_common_context(manor)
    running_tournaments = list(
        ArenaTournament.objects.filter(status=ArenaTournament.Status.RUNNING)
        .annotate(
            total_entries=Count("entries"),
            active_entries=Count("entries", filter=Q(entries__status=ArenaEntry.Status.REGISTERED)),
        )
        .order_by("next_round_at", "id")[:20]
    )

    my_tournament_ids = set(
        ArenaEntry.objects.filter(
            manor=manor,
            tournament_id__in=[tournament.id for tournament in running_tournaments],
        ).values_list("tournament_id", flat=True)
    )

    running_rows = [
        {
            "tournament": tournament,
            "is_mine": tournament.id in my_tournament_ids,
        }
        for tournament in running_tournaments
    ]
    running_rows.sort(key=_running_row_sort_key)
    context["running_tournaments"] = running_rows
    return context


def get_arena_exchange_context(manor: Manor) -> dict:
    context = _build_common_context(manor)
    context["reward_rows"] = _build_reward_rows(manor)
    context["recent_exchange_records"] = ArenaExchangeRecord.objects.filter(manor=manor).order_by("-created_at")[:15]
    return context


def get_arena_event_detail_context(manor: Manor, tournament_id: int, selected_round: int | None = None) -> dict | None:
    context = _build_common_context(manor)
    current_time = timezone.now()
    tournament = (
        ArenaTournament.objects.annotate(
            total_entries=Count("entries"),
            active_entries=Count("entries", filter=Q(entries__status=ArenaEntry.Status.REGISTERED)),
        )
        .filter(pk=tournament_id)
        .first()
    )
    if not tournament:
        return None

    if tournament.status != ArenaTournament.Status.RUNNING:
        visible_cutoff = current_time - timedelta(seconds=arena_core.ARENA_COMPLETED_RETENTION_SECONDS)
        is_recently_ended = (
            tournament.status in [ArenaTournament.Status.COMPLETED, ArenaTournament.Status.CANCELLED]
            and tournament.ended_at is not None
            and tournament.ended_at >= visible_cutoff
        )
        if not is_recently_ended:
            return None

    is_mine = ArenaEntry.objects.filter(tournament=tournament, manor=manor).exists()

    all_matches = list(
        ArenaMatch.objects.select_related(
            "attacker_entry__manor",
            "defender_entry__manor",
            "winner_entry__manor",
            "battle_report",
        )
        .filter(tournament=tournament)
        .order_by("round_number", "match_index", "id")
    )

    available_rounds = sorted({match.round_number for match in all_matches})
    current_round = None
    if available_rounds:
        if selected_round in available_rounds:
            current_round = selected_round
        else:
            current_round = available_rounds[-1]

    current_round_match_rows: list[dict] = []
    if current_round is not None:
        for match in all_matches:
            if match.round_number != current_round:
                continue
            left_name = match.attacker_entry.manor.display_name
            right_name = match.defender_entry.manor.display_name if match.defender_entry else "轮空"
            left_is_loser = (
                match.defender_entry_id is not None
                and match.winner_entry_id is not None
                and match.winner_entry_id != match.attacker_entry_id
            )
            right_is_loser = (
                match.defender_entry_id is not None
                and match.winner_entry_id is not None
                and match.winner_entry_id != match.defender_entry_id
            )
            left_outcome = None
            right_outcome = None
            if match.winner_entry_id is not None:
                if match.winner_entry_id == match.attacker_entry_id:
                    left_outcome = "胜利"
                elif match.defender_entry_id is not None:
                    left_outcome = "战败"
                if match.defender_entry_id is not None:
                    if match.winner_entry_id == match.defender_entry_id:
                        right_outcome = "胜利"
                    else:
                        right_outcome = "战败"

            current_round_match_rows.append(
                {
                    "match": match,
                    "left_name": left_name,
                    "right_name": right_name,
                    "left_is_loser": left_is_loser,
                    "right_is_loser": right_is_loser,
                    "left_outcome": left_outcome,
                    "right_outcome": right_outcome,
                    "left_is_mine": match.attacker_entry.manor_id == manor.id,
                    "right_is_mine": match.defender_entry is not None and match.defender_entry.manor_id == manor.id,
                    "report_id": match.battle_report_id,
                }
            )

    previous_round_number = None
    next_round_number = None
    if current_round is not None and available_rounds:
        current_index = available_rounds.index(current_round)
        if current_index > 0:
            previous_round_number = available_rounds[current_index - 1]
        if current_index < len(available_rounds) - 1:
            next_round_number = available_rounds[current_index + 1]

    context.update(
        {
            "tournament": tournament,
            "round_pages": [
                {
                    "round": round_number,
                    "is_active": round_number == current_round,
                }
                for round_number in available_rounds
            ],
            "current_round_number": current_round,
            "current_round_match_rows": current_round_match_rows,
            "previous_round_number": previous_round_number,
            "next_round_number": next_round_number,
            "is_mine": is_mine,
        }
    )
    return context


def get_arena_context(manor: Manor) -> dict:
    """
    Backward-compatible aggregator for legacy callers.

    Prefer page-specific selectors:
    - get_arena_registration_context
    - get_arena_events_context
    - get_arena_exchange_context
    """

    context = get_arena_registration_context(manor)
    events_context = get_arena_events_context(manor)
    exchange_context = get_arena_exchange_context(manor)
    context.update(
        {
            "running_tournaments": events_context.get("running_tournaments", []),
            "reward_rows": exchange_context.get("reward_rows", []),
        }
    )
    return context
