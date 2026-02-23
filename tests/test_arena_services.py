from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from gameplay.models import (
    ArenaEntry,
    ArenaEntryGuest,
    ArenaExchangeRecord,
    ArenaMatch,
    ArenaTournament,
    Manor,
    Message,
)
from gameplay.services.arena import core as arena_core
from gameplay.services.arena.core import (
    exchange_arena_reward,
    register_arena_entry,
    run_due_arena_rounds,
    start_tournament_if_ready,
)
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestStatus, GuestTemplate

User = get_user_model()


def _create_guest_template(key: str) -> GuestTemplate:
    return GuestTemplate.objects.create(
        key=key,
        name=f"测试门客-{key}",
        archetype="military",
        rarity="green",
        base_attack=120,
        base_intellect=90,
        base_defense=100,
        base_agility=90,
        base_luck=50,
        base_hp=1500,
    )


def _create_guest(manor: Manor, template: GuestTemplate, suffix: str) -> Guest:
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        custom_name=f"门客{suffix}",
        level=30,
        force=180,
        intellect=120,
        defense_stat=150,
        agility=130,
        current_hp=1,
    )
    guest.current_hp = guest.max_hp
    guest.save(update_fields=["current_hp"])
    return guest


def _snapshot_from_guest(guest: Guest) -> dict:
    stats = guest.stat_block()
    return {
        "template_key": guest.template.key,
        "display_name": guest.display_name,
        "rarity": guest.rarity,
        "level": guest.level,
        "force": guest.force,
        "intellect": guest.intellect,
        "defense_stat": guest.defense_stat,
        "agility": guest.agility,
        "luck": guest.luck,
        "attack": stats["attack"],
        "defense": stats["defense"],
        "max_hp": guest.max_hp,
        "current_hp": guest.current_hp,
        "skill_keys": [],
    }


@pytest.mark.django_db
def test_register_arena_entry_respects_daily_limit():
    user = User.objects.create_user(
        username="arena_daily_limit",
        password="pass123",
        email="arena_daily_limit@test.local",
    )
    manor = ensure_manor(user)
    template = _create_guest_template("arena_daily_limit_tpl")
    guest = _create_guest(manor, template, "A")

    now = timezone.now()
    for idx in range(3):
        tournament = ArenaTournament.objects.create(
            status=ArenaTournament.Status.COMPLETED,
            player_limit=10,
            round_interval_seconds=600,
            ended_at=now,
        )
        ArenaEntry.objects.create(
            tournament=tournament,
            manor=manor,
            status=ArenaEntry.Status.ELIMINATED,
            final_rank=10 - idx,
            coin_reward=10,
        )

    with pytest.raises(ValueError, match="每日最多参加"):
        register_arena_entry(manor, [guest.id])


@pytest.mark.django_db
def test_register_arena_entry_rejects_more_than_ten_guests():
    user = User.objects.create_user(
        username="arena_guest_limit",
        password="pass123",
        email="arena_guest_limit@test.local",
    )
    manor = ensure_manor(user)
    template = _create_guest_template("arena_guest_limit_tpl")
    guests = [_create_guest(manor, template, str(i)) for i in range(11)]

    with pytest.raises(ValueError, match="最多选择 10 名门客"):
        register_arena_entry(manor, [guest.id for guest in guests])


@pytest.mark.django_db
def test_register_arena_entry_requires_idle_guests():
    user = User.objects.create_user(
        username="arena_guest_status",
        password="pass123",
        email="arena_guest_status@test.local",
    )
    manor = ensure_manor(user)
    template = _create_guest_template("arena_guest_status_tpl")
    guest = _create_guest(manor, template, "A")
    guest.status = GuestStatus.WORKING
    guest.save(update_fields=["status"])

    with pytest.raises(ValueError, match="仅空闲门客可报名竞技场"):
        register_arena_entry(manor, [guest.id])


@pytest.mark.django_db
def test_register_arena_entry_returns_busy_error_when_recruiting_lock_not_acquired(monkeypatch):
    user = User.objects.create_user(
        username="arena_lock_busy",
        password="pass123",
        email="arena_lock_busy@test.local",
    )
    manor = ensure_manor(user)
    template = _create_guest_template("arena_lock_busy_tpl")
    guest = _create_guest(manor, template, "A")

    monkeypatch.setattr(arena_core, "acquire_best_effort_lock", lambda *args, **kwargs: (False, False))

    with pytest.raises(ValueError, match="竞技场报名繁忙，请稍后重试"):
        register_arena_entry(manor, [guest.id])


@pytest.mark.django_db
def test_register_arena_entry_auto_starts_when_reaching_ten_players():
    template = _create_guest_template("arena_auto_start_tpl")

    tournament_id = None
    for idx in range(10):
        user = User.objects.create_user(
            username=f"arena_auto_{idx}",
            password="pass123",
            email=f"arena_auto_{idx}@test.local",
        )
        manor = ensure_manor(user)
        guest = _create_guest(manor, template, str(idx))
        result = register_arena_entry(manor, [guest.id])
        guest.refresh_from_db(fields=["status"])
        assert guest.status == GuestStatus.DEPLOYED

        if tournament_id is None:
            tournament_id = result.tournament.id
        assert result.tournament.id == tournament_id

        if idx < 9:
            assert result.auto_started is False
        else:
            assert result.auto_started is True

    tournament = ArenaTournament.objects.get(pk=tournament_id)
    assert tournament.status == ArenaTournament.Status.RUNNING
    assert tournament.entries.count() == 10


@pytest.mark.django_db
def test_run_due_arena_rounds_completes_tournament_and_grants_coins():
    template = _create_guest_template("arena_round_tpl")

    user_a = User.objects.create_user(username="arena_round_a", password="pass123", email="arena_round_a@test.local")
    user_b = User.objects.create_user(username="arena_round_b", password="pass123", email="arena_round_b@test.local")
    manor_a = ensure_manor(user_a)
    manor_b = ensure_manor(user_b)
    guest_a = _create_guest(manor_a, template, "A")
    guest_b = _create_guest(manor_b, template, "B")

    now = timezone.now()
    tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RUNNING,
        player_limit=2,
        round_interval_seconds=600,
        current_round=0,
        started_at=now,
        next_round_at=now - timedelta(seconds=1),
    )
    entry_a = ArenaEntry.objects.create(tournament=tournament, manor=manor_a)
    entry_b = ArenaEntry.objects.create(tournament=tournament, manor=manor_b)
    ArenaEntryGuest.objects.create(entry=entry_a, guest=guest_a)
    ArenaEntryGuest.objects.create(entry=entry_b, guest=guest_b)

    processed = run_due_arena_rounds(now=now, limit=10)
    assert processed == 1

    tournament.refresh_from_db()
    assert tournament.status == ArenaTournament.Status.COMPLETED
    assert tournament.winner_entry_id in {entry_a.id, entry_b.id}
    assert ArenaMatch.objects.filter(tournament=tournament).count() == 1

    entry_a.refresh_from_db()
    entry_b.refresh_from_db()
    assert {entry_a.final_rank, entry_b.final_rank} == {1, 2}
    assert entry_a.coin_reward > 0
    assert entry_b.coin_reward > 0

    manor_a.refresh_from_db(fields=["arena_coins"])
    manor_b.refresh_from_db(fields=["arena_coins"])
    assert manor_a.arena_coins > 0
    assert manor_b.arena_coins > 0
    assert Message.objects.filter(manor=manor_a).exists()
    assert Message.objects.filter(manor=manor_b).exists()


@pytest.mark.django_db
def test_arena_uses_guest_snapshot_not_live_guest_state():
    template = _create_guest_template("arena_snapshot_tpl")
    user_a = User.objects.create_user(
        username="arena_snapshot_a",
        password="pass123",
        email="arena_snapshot_a@test.local",
    )
    user_b = User.objects.create_user(
        username="arena_snapshot_b",
        password="pass123",
        email="arena_snapshot_b@test.local",
    )
    manor_a = ensure_manor(user_a)
    manor_b = ensure_manor(user_b)
    guest_a = _create_guest(manor_a, template, "A")
    guest_b = _create_guest(manor_b, template, "B")

    first = register_arena_entry(manor_a, [guest_a.id])
    tournament = first.tournament
    tournament.player_limit = 2
    tournament.save(update_fields=["player_limit"])

    register_arena_entry(manor_b, [guest_b.id])
    start_tournament_if_ready(tournament)

    # 报名后修改实时门客数据，不应影响竞技场对战快照
    guest_a.level = 99
    guest_a.force = 9999
    guest_a.save(update_fields=["level", "force"])

    now = timezone.now()
    tournament.refresh_from_db()
    tournament.next_round_at = now - timedelta(seconds=1)
    tournament.save(update_fields=["next_round_at"])
    run_due_arena_rounds(now=now, limit=10)

    match = ArenaMatch.objects.filter(tournament=tournament, battle_report__isnull=False).first()
    assert match is not None
    report = match.battle_report
    levels = [member.get("level") for member in (report.attacker_team + report.defender_team)]
    assert 99 not in levels
    guest_a.refresh_from_db(fields=["status"])
    guest_b.refresh_from_db(fields=["status"])
    assert guest_a.status == GuestStatus.IDLE
    assert guest_b.status == GuestStatus.IDLE


@pytest.mark.django_db
def test_arena_no_fallback_when_registered_guest_missing():
    template = _create_guest_template("arena_no_fallback_tpl")
    user_a = User.objects.create_user(
        username="arena_no_fallback_a",
        password="pass123",
        email="arena_no_fallback_a@test.local",
    )
    user_b = User.objects.create_user(
        username="arena_no_fallback_b",
        password="pass123",
        email="arena_no_fallback_b@test.local",
    )
    manor_a = ensure_manor(user_a)
    manor_b = ensure_manor(user_b)

    guest_a = _create_guest(manor_a, template, "A")
    backup_guest = _create_guest(manor_a, template, "A2")
    guest_b = _create_guest(manor_b, template, "B")
    # 保证 backup_guest 不在报名快照内
    backup_guest.level = 88
    backup_guest.save(update_fields=["level"])

    now = timezone.now()
    tournament = ArenaTournament.objects.create(
        status=ArenaTournament.Status.RUNNING,
        player_limit=2,
        round_interval_seconds=600,
        current_round=0,
        started_at=now,
        next_round_at=now - timedelta(seconds=1),
    )
    entry_a = ArenaEntry.objects.create(tournament=tournament, manor=manor_a)
    entry_b = ArenaEntry.objects.create(tournament=tournament, manor=manor_b)
    ArenaEntryGuest.objects.create(
        entry=entry_a,
        guest=guest_a,
        snapshot=_snapshot_from_guest(guest_a),
    )
    ArenaEntryGuest.objects.create(
        entry=entry_b,
        guest=guest_b,
        snapshot=_snapshot_from_guest(guest_b),
    )
    # 模拟报名门客丢失（报名关联被删），不应回退使用 backup_guest
    ArenaEntryGuest.objects.filter(entry=entry_a).delete()

    run_due_arena_rounds(now=now, limit=10)
    match = ArenaMatch.objects.filter(tournament=tournament).first()
    assert match is not None
    assert match.status == ArenaMatch.Status.FORFEIT
    assert match.winner_entry_id == entry_b.id


@pytest.mark.django_db
def test_exchange_arena_reward_deducts_coins_and_creates_record():
    user = User.objects.create_user(username="arena_exchange", password="pass123", email="arena_exchange@test.local")
    manor = ensure_manor(user)
    manor.arena_coins = 1000
    manor.save(update_fields=["arena_coins"])
    initial_grain = manor.grain

    result = exchange_arena_reward(manor, "grain_pack_small", quantity=2)

    manor.refresh_from_db()
    assert result.total_cost == 160
    assert manor.arena_coins == 840
    assert manor.grain > initial_grain
    assert ArenaExchangeRecord.objects.filter(manor=manor, reward_key="grain_pack_small").count() == 1
