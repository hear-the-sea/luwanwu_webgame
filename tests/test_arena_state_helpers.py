from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from gameplay.models import ArenaEntry, ArenaTournament
from gameplay.services.arena.state_helpers import (
    sync_daily_participation_counter_locked,
    update_daily_participation_counter_locked,
)
from gameplay.services.manor.core import ensure_manor

User = get_user_model()


@pytest.mark.django_db
def test_sync_daily_participation_counter_locked_uses_existing_same_day_counter():
    user = User.objects.create_user(username="arena_state_same_day", password="pass123")
    manor = ensure_manor(user)
    today = timezone.localdate()
    manor.arena_participation_date = today
    manor.arena_participations_today = 3
    manor.save(update_fields=["arena_participation_date", "arena_participations_today"])

    value = sync_daily_participation_counter_locked(manor)

    assert value == 3


@pytest.mark.django_db
def test_sync_daily_participation_counter_locked_backfills_from_today_entries():
    user = User.objects.create_user(username="arena_state_backfill", password="pass123")
    manor = ensure_manor(user)
    manor.arena_participation_date = timezone.localdate() - timedelta(days=1)
    manor.arena_participations_today = 9
    manor.save(update_fields=["arena_participation_date", "arena_participations_today"])

    tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RECRUITING,
        player_limit=2,
        round_interval_seconds=600,
    )
    second_tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RECRUITING,
        player_limit=2,
        round_interval_seconds=600,
    )
    ArenaEntry.objects.create(tournament=tournament, manor=manor)
    ArenaEntry.objects.create(tournament=second_tournament, manor=manor)

    value = sync_daily_participation_counter_locked(manor)
    manor.refresh_from_db(fields=["arena_participation_date", "arena_participations_today"])

    assert value == 2
    assert manor.arena_participation_date == timezone.localdate()
    assert manor.arena_participations_today == 2


@pytest.mark.django_db
def test_update_daily_participation_counter_locked_clamps_at_zero():
    user = User.objects.create_user(username="arena_state_clamp", password="pass123")
    manor = ensure_manor(user)
    manor.arena_participation_date = timezone.localdate()
    manor.arena_participations_today = 1
    manor.save(update_fields=["arena_participation_date", "arena_participations_today"])

    value = update_daily_participation_counter_locked(manor, delta=-5)
    manor.refresh_from_db(fields=["arena_participations_today"])

    assert value == 0
    assert manor.arena_participations_today == 0
