from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from battle.models import BattleReport
from gameplay.models import ArenaEntry, ArenaMatch, ArenaTournament
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
def test_arena_report_uses_defender_perspective_for_defender_viewer(client, django_user_model):
    attacker_user = django_user_model.objects.create_user(
        username="arena_report_attacker",
        password="pass123",
        email="arena_report_attacker@test.local",
    )
    defender_user = django_user_model.objects.create_user(
        username="arena_report_defender",
        password="pass123",
        email="arena_report_defender@test.local",
    )
    attacker_manor = ensure_manor(attacker_user)
    defender_manor = ensure_manor(defender_user)

    now = timezone.now()
    report = BattleReport.objects.create(
        manor=attacker_manor,
        opponent_name=defender_manor.display_name,
        battle_type="arena",
        attacker_team=[{"name": "A", "guest_id": 1, "template_key": "a"}],
        attacker_troops={},
        defender_team=[{"name": "D", "guest_id": 2, "template_key": "d"}],
        defender_troops={},
        rounds=[],
        losses={"attacker": {}, "defender": {}},
        drops={},
        winner="attacker",
        starts_at=now,
        completed_at=now,
        seed=1,
    )
    tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RUNNING,
        player_limit=10,
        round_interval_seconds=600,
        started_at=now,
        next_round_at=now,
    )
    attacker_entry = ArenaEntry.objects.create(tournament=tournament, manor=attacker_manor)
    defender_entry = ArenaEntry.objects.create(tournament=tournament, manor=defender_manor)
    ArenaMatch.objects.create(
        tournament=tournament,
        round_number=1,
        match_index=0,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        winner_entry=attacker_entry,
        status=ArenaMatch.Status.COMPLETED,
        battle_report=report,
        resolved_at=now,
    )

    assert client.login(username="arena_report_defender", password="pass123")
    response = client.get(reverse("battle:report_detail", kwargs={"pk": report.pk}))

    assert response.status_code == 200
    assert response.context["player_side"] == "defender"
