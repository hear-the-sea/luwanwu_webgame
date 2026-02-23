from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from gameplay.models import ArenaEntry, ArenaMatch, ArenaTournament, Manor
from gameplay.services.arena.core import ARENA_DAILY_PARTICIPATION_LIMIT, ARENA_MAX_GUESTS_PER_ENTRY
from gameplay.services.arena.rewards import load_arena_reward_catalog


def _build_reward_rows(manor: Manor) -> list[dict]:
    catalog = load_arena_reward_catalog()
    rows: list[dict] = []
    for reward in catalog.values():
        rows.append(
            {
                "key": reward.key,
                "name": reward.name,
                "description": reward.description,
                "cost_coins": reward.cost_coins,
                "daily_limit": reward.daily_limit,
                "resources": reward.resources,
                "items": reward.items,
                "can_afford": manor.arena_coins >= reward.cost_coins,
            }
        )
    rows.sort(key=lambda item: (item["cost_coins"], item["key"]))
    return rows


def get_arena_context(manor: Manor) -> dict:
    today = timezone.localdate()
    today_participations = ArenaEntry.objects.filter(manor=manor, joined_at__date=today).count()
    remaining_daily = max(0, ARENA_DAILY_PARTICIPATION_LIMIT - today_participations)

    active_entry = (
        ArenaEntry.objects.select_related("tournament")
        .prefetch_related("entry_guests__guest")
        .filter(manor=manor, tournament__status__in=[ArenaTournament.Status.RECRUITING, ArenaTournament.Status.RUNNING])
        .order_by("-joined_at")
        .first()
    )

    recruiting_tournament = (
        ArenaTournament.objects.filter(status=ArenaTournament.Status.RECRUITING)
        .annotate(entry_count=Count("entries"))
        .order_by("created_at")
        .first()
    )

    running_tournaments = (
        ArenaTournament.objects.filter(status=ArenaTournament.Status.RUNNING)
        .annotate(
            total_entries=Count("entries"),
            active_entries=Count("entries", filter=Q(entries__status=ArenaEntry.Status.REGISTERED)),
        )
        .order_by("next_round_at", "id")[:5]
    )

    recent_matches = ArenaMatch.objects.select_related(
        "tournament",
        "attacker_entry__manor",
        "defender_entry__manor",
        "winner_entry__manor",
        "battle_report",
    ).order_by("-created_at")[:30]

    my_recent_entries = ArenaEntry.objects.select_related("tournament").filter(manor=manor).order_by("-joined_at")[:10]

    available_guests = manor.guests.select_related("template").order_by("-level", "id")
    selected_guest_ids: set[int] = set()
    if active_entry:
        selected_guest_ids = set(active_entry.entry_guests.values_list("guest_id", flat=True))

    return {
        "manor": manor,
        "today_participations": today_participations,
        "remaining_daily": remaining_daily,
        "daily_limit": ARENA_DAILY_PARTICIPATION_LIMIT,
        "max_guests_per_entry": ARENA_MAX_GUESTS_PER_ENTRY,
        "active_entry": active_entry,
        "recruiting_tournament": recruiting_tournament,
        "running_tournaments": running_tournaments,
        "recent_matches": recent_matches,
        "my_recent_entries": my_recent_entries,
        "available_guests": available_guests,
        "selected_guest_ids": selected_guest_ids,
        "reward_rows": _build_reward_rows(manor),
    }
