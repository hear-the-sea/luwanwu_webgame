from __future__ import annotations

import contextlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from gameplay.models import RaidRun
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.combat import battle as combat_battle
from guests.models import Guest, GuestStatus, GuestTemplate


def test_normalize_mapping_returns_dict_when_valid():
    result = combat_battle._normalize_mapping({"a": 1, "b": 2})
    assert result == {"a": 1, "b": 2}


def test_normalize_mapping_returns_empty_dict_when_invalid():
    assert combat_battle._normalize_mapping(None) == {}
    assert combat_battle._normalize_mapping("string") == {}
    assert combat_battle._normalize_mapping(123) == {}
    assert combat_battle._normalize_mapping([1, 2, 3]) == {}


def test_coerce_positive_int_returns_int_when_valid():
    assert combat_battle._coerce_positive_int(10) == 10
    assert combat_battle._coerce_positive_int("20") == 20
    assert combat_battle._coerce_positive_int(5.7) == 5


def test_coerce_positive_int_returns_zero_when_negative():
    assert combat_battle._coerce_positive_int(-5) == 0
    assert combat_battle._coerce_positive_int(0) == 0


def test_coerce_positive_int_returns_default_when_invalid():
    assert combat_battle._coerce_positive_int(None, default=10) == 10
    assert combat_battle._coerce_positive_int("invalid", default=5) == 5
    assert combat_battle._coerce_positive_int({}, default=3) == 3


def test_normalize_positive_int_mapping_filters_invalid_keys():
    raw = {"": 10, None: 20, "  ": 30, "valid": 40}
    result = combat_battle._normalize_positive_int_mapping(raw)
    assert result == {"valid": 40}


def test_normalize_positive_int_mapping_filters_non_positive_values():
    raw = {"a": 10, "b": 0, "c": -5, "d": "invalid", "e": 20}
    result = combat_battle._normalize_positive_int_mapping(raw)
    assert result == {"a": 10, "e": 20}


def test_normalize_positive_int_mapping_handles_non_dict():
    assert combat_battle._normalize_positive_int_mapping(None) == {}
    assert combat_battle._normalize_positive_int_mapping("string") == {}
    assert combat_battle._normalize_positive_int_mapping([1, 2, 3]) == {}


def test_resolve_capture_sides_attacker_wins():
    run = SimpleNamespace(attacker=SimpleNamespace(id=1), defender=SimpleNamespace(id=2))
    winner, loser = combat_battle._resolve_capture_sides(run, is_attacker_victory=True)
    assert winner.id == 1
    assert loser.id == 2


def test_resolve_capture_sides_defender_wins():
    run = SimpleNamespace(attacker=SimpleNamespace(id=1), defender=SimpleNamespace(id=2))
    winner, loser = combat_battle._resolve_capture_sides(run, is_attacker_victory=False)
    assert winner.id == 2
    assert loser.id == 1


def test_collect_losing_guest_ids_attacker_victory():
    report = SimpleNamespace(defender_team=[{"guest_id": 123}, {"guest_id": 456}], attacker_team=[])
    result = combat_battle._collect_losing_guest_ids(report, is_attacker_victory=True)
    assert set(result) == {123, 456}


def test_collect_losing_guest_ids_defender_victory():
    report = SimpleNamespace(attacker_team=[{"guest_id": 789}], defender_team=[])
    result = combat_battle._collect_losing_guest_ids(report, is_attacker_victory=False)
    assert result == [789]


def test_collect_losing_guest_ids_handles_invalid_data():
    report = SimpleNamespace(defender_team=[{"guest_id": "invalid"}, {"guest_id": 999}, {}], attacker_team=[])
    result = combat_battle._collect_losing_guest_ids(report, is_attacker_victory=True)
    assert result == [999]


def test_dispatch_complete_raid_task_uses_remaining_return_time(monkeypatch):
    now = timezone.now()
    captured: dict[str, object] = {}

    def _fake_safe_apply_async(task, args, countdown, logger, log_message):
        captured["task"] = task
        captured["args"] = args
        captured["countdown"] = countdown

    import gameplay.tasks as gameplay_tasks

    fake_complete_task = object()
    monkeypatch.setattr(gameplay_tasks, "complete_raid_task", fake_complete_task, raising=False)
    monkeypatch.setattr(combat_battle, "safe_apply_async", _fake_safe_apply_async)

    run = SimpleNamespace(id=42, return_at=now + timedelta(seconds=37), travel_time=600)
    combat_battle._dispatch_complete_raid_task(run, now=now)

    assert captured["task"] is fake_complete_task
    assert captured["args"] == [42]
    assert captured["countdown"] == 37


def test_process_raid_battle_ignores_post_commit_failures(monkeypatch):
    now = timezone.now()
    attacker = SimpleNamespace(id=1, location_display="江南", display_name="进攻方")
    defender = SimpleNamespace(id=2, location_display="塞北", display_name="防守方")
    saved = {"count": 0}
    dispatched = {"count": 0}
    run = SimpleNamespace(
        pk=7,
        id=7,
        attacker_id=1,
        defender_id=2,
        attacker=attacker,
        defender=defender,
        status=RaidRun.Status.MARCHING,
        save=lambda **_kwargs: saved.__setitem__("count", saved["count"] + 1),
    )
    report = SimpleNamespace(winner="attacker")

    monkeypatch.setattr(combat_battle.transaction, "atomic", contextlib.nullcontext)
    monkeypatch.setattr(combat_battle, "_prepare_run_for_battle", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(combat_battle, "_lock_battle_manors", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_battle, "_execute_raid_battle", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(combat_battle, "apply_defender_troop_losses", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_raid_loot_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_prestige_changes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_defeat_protection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_capture_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_salvage_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        combat_battle,
        "_send_raid_battle_messages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("messages down")),
    )
    monkeypatch.setattr(
        combat_battle,
        "_dismiss_marching_raids_if_protected",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dismiss down")),
    )
    monkeypatch.setattr(
        combat_battle,
        "_dispatch_complete_raid_task",
        lambda *_args, **_kwargs: dispatched.__setitem__("count", dispatched["count"] + 1),
    )

    combat_battle.process_raid_battle(run, now=now)

    assert run.status == RaidRun.Status.RETURNING
    assert saved["count"] == 1
    assert dispatched["count"] == 1


@pytest.mark.django_db
def test_apply_defeat_protection_sets_defender_until(django_user_model):
    attacker_user = django_user_model.objects.create_user(username="raid_defeat_attacker", password="pass123")
    defender_user = django_user_model.objects.create_user(username="raid_defeat_defender", password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    run = RaidRun.objects.create(attacker=attacker, defender=defender)
    now = timezone.now()
    combat_battle._apply_defeat_protection(run, is_attacker_victory=True, now=now)

    defender.refresh_from_db()
    expected = now + timedelta(seconds=combat_battle.combat_pkg.PVPConstants.RAID_DEFEAT_PROTECTION_SECONDS)
    assert defender.defeat_protection_until is not None
    assert abs((defender.defeat_protection_until - expected).total_seconds()) <= 1


@pytest.mark.django_db
def test_execute_raid_battle_uses_attacker_snapshot(monkeypatch, django_user_model):
    attacker_user = django_user_model.objects.create_user(username="raid_snapshot_a", password="pass123")
    defender_user = django_user_model.objects.create_user(username="raid_snapshot_d", password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    template = GuestTemplate.objects.create(
        key="raid_snapshot_tpl",
        name="踢馆快照门客",
        archetype="military",
        rarity="green",
        base_attack=120,
        base_intellect=90,
        base_defense=100,
        base_agility=90,
        base_luck=50,
        base_hp=1500,
    )
    attacker_guest = Guest.objects.create(
        manor=attacker,
        template=template,
        status=GuestStatus.DEPLOYED,
        level=20,
        force=300,
        intellect=120,
        defense_stat=130,
        agility=110,
        current_hp=900,
    )
    defender_guest = Guest.objects.create(
        manor=defender,
        template=template,
        status=GuestStatus.IDLE,
        level=10,
        force=120,
        intellect=100,
        defense_stat=110,
        agility=90,
        current_hp=700,
    )
    attacker_stats = attacker_guest.stat_block()
    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        status=RaidRun.Status.MARCHING,
        troop_loadout={},
        travel_time=60,
        battle_at=timezone.now(),
        return_at=timezone.now(),
        guest_snapshots=[
            {
                "guest_id": attacker_guest.id,
                "template_key": template.key,
                "display_name": attacker_guest.display_name,
                "rarity": attacker_guest.rarity,
                "status": "deployed",
                "level": 20,
                "force": 300,
                "intellect": 120,
                "defense_stat": 130,
                "agility": 110,
                "luck": 50,
                "attack": int(attacker_stats["attack"]),
                "defense": int(attacker_stats["defense"]),
                "max_hp": attacker_guest.max_hp,
                "current_hp": 900,
                "troop_capacity": int(getattr(attacker_guest, "troop_capacity", 0) or 0),
                "skill_keys": [],
            }
        ],
    )
    run.guests.add(attacker_guest)

    # 报名后实时属性变化，不应影响战斗结算输入快照
    attacker_guest.level = 99
    attacker_guest.force = 9999
    attacker_guest.save(update_fields=["level", "force"])

    captured = {}

    def _fake_simulate_report(**kwargs):
        attacker_guests = kwargs.get("attacker_guests") or []
        assert attacker_guests
        captured["level"] = attacker_guests[0].level
        captured["force"] = attacker_guests[0].force
        captured["guest_id"] = attacker_guests[0].id
        return SimpleNamespace(
            winner="attacker",
            attacker_team=[{"guest_id": attacker_guest.id, "remaining_hp": 500}],
            defender_team=[{"guest_id": defender_guest.id, "remaining_hp": 300}],
            losses={
                "attacker": {"hp_updates": {str(attacker_guest.id): 500}},
                "defender": {"hp_updates": {str(defender_guest.id): 300}},
            },
        )

    monkeypatch.setattr("battle.services.simulate_report", _fake_simulate_report)

    combat_battle._execute_raid_battle(run)

    attacker_guest.refresh_from_db()
    assert captured["level"] == 20
    assert captured["force"] == 300
    assert captured["guest_id"] == attacker_guest.id
    assert attacker_guest.current_hp == 500
