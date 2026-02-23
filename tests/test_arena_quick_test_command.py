from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from gameplay.models import ArenaEntry, ArenaTournament


@pytest.mark.django_db
def test_arena_quick_test_command_fills_existing_recruiting_pool_and_starts():
    tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RECRUITING,
        player_limit=2,
        round_interval_seconds=600,
    )
    out = StringIO()

    call_command("arena_quick_test", verbosity=0, stdout=out)

    tournament.refresh_from_db()
    assert tournament.status == ArenaTournament.Status.RUNNING
    assert ArenaEntry.objects.filter(tournament=tournament).count() == 2
    assert "竞技场快速测试完成" in out.getvalue()


@pytest.mark.django_db
def test_arena_quick_test_command_can_finish_tournament():
    tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RECRUITING,
        player_limit=2,
        round_interval_seconds=600,
    )
    out = StringIO()

    call_command(
        "arena_quick_test",
        finish=True,
        max_steps=10,
        step_seconds=600,
        verbosity=0,
        stdout=out,
    )

    tournament.refresh_from_db()
    assert tournament.status == ArenaTournament.Status.COMPLETED
    assert tournament.ended_at is not None
    assert ArenaEntry.objects.filter(tournament=tournament, final_rank__isnull=False).count() == 2
