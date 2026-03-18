import random

import pytest
from django.utils import timezone

from battle.models import BattleReport
from battle.services import (
    BATTLE_ORPHANED_DEPLOYED_RECOVERY_COUNTER,
    _build_defender_guest_and_loadout,
    _extract_defender_tech_profile,
    recover_orphaned_deployed_guests,
    simulate_report,
)
from core.exceptions import GuestNotIdleError
from gameplay.models import ArenaEntry, ArenaEntryGuest, ArenaTournament, MissionRun, MissionTemplate, RaidRun
from gameplay.services.battle_snapshots import build_guest_battle_snapshots, build_guest_snapshot_proxies
from gameplay.services.manor.core import ensure_manor
from guests.models import GuestStatus, RecruitmentPool
from guests.services.health import INJURY_RECOVERY_THRESHOLD, heal_guest
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate


def _recruit_frontline(manor, draws: int = 3) -> None:
    pool = RecruitmentPool.objects.get(key="cunmu")
    for seed in range(draws):
        candidates = recruit_guest(manor, pool, seed=seed + 1)
        finalize_candidate(candidates[0])


@pytest.mark.django_db
def test_simulate_report_creates_battle(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="general", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.save()
    _recruit_frontline(manor)
    # 3名门客可带600人，配置合理的兵力
    troop_loadout = {"dao_jie": 100, "qiang_ling": 100, "archer": 100, "fist_master": 100, "jian_shi": 100}
    report = simulate_report(manor, seed=2, troop_loadout=troop_loadout)
    assert isinstance(report, BattleReport)
    assert len(report.rounds) > 0
    assert report.battle_type == "skirmish"
    assert "attacker" in report.losses
    assert "defender" in report.losses
    assert isinstance(report.drops, dict)
    first_round = report.rounds[0]
    assert first_round["round"] == 1
    assert first_round["events"]
    orders = [event["order"] for event in first_round["events"]]
    assert orders == list(range(1, len(orders) + 1))
    assert any(event.get("status") == "charging" for event in first_round["events"])
    assert any(event.get("preemptive") for event in first_round["events"])
    assert all("agility" in event for event in first_round["events"] if "damage" in event)
    assert sum(report.attacker_troops.values()) > 0
    assert report.attacker_team and all("initial_hp" in e and "level" in e for e in report.attacker_team)
    assert report.defender_team and all("initial_hp" in e and "level" in e for e in report.defender_team)


@pytest.mark.django_db
def test_simulate_report_attacker_victory_increases_guest_loyalty(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="battle_loyalty", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.save()
    _recruit_frontline(manor, draws=4)

    for guest in manor.guests.all():
        guest.level = 50
        guest.attack_bonus = 800
        guest.defense_bonus = 800
        guest.intellect = 800
        guest.force = 800
        guest.defense_stat = 300
        guest.current_hp = guest.max_hp
        guest.loyalty = 50
        guest.save()

    troop_loadout = {"dao_jie": 150, "qiang_ling": 150, "archer": 150, "fist_master": 150, "jian_shi": 150}
    report = simulate_report(
        manor, seed=1, max_squad=getattr(manor, "max_squad_size", None), troop_loadout=troop_loadout
    )

    assert report.winner == "attacker"
    assert set(manor.guests.values_list("loyalty", flat=True)) == {51}


@pytest.mark.django_db
def test_simulate_report_rejects_foreign_attacker_guests(game_data, django_user_model):
    attacker_user = django_user_model.objects.create_user(username="battle_owner", password="pass123")
    foreign_user = django_user_model.objects.create_user(username="battle_foreign", password="pass123")
    attacker_manor = ensure_manor(attacker_user)
    foreign_manor = ensure_manor(foreign_user)

    _recruit_frontline(attacker_manor, draws=1)
    _recruit_frontline(foreign_manor, draws=1)
    foreign_guest = foreign_manor.guests.first()

    with pytest.raises(ValueError, match="攻击方门客必须属于当前庄园"):
        simulate_report(attacker_manor, attacker_guests=[foreign_guest], troop_loadout={})


@pytest.mark.django_db
def test_simulate_report_accepts_legacy_snapshot_guests_without_db_ownership_lookup(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="battle_snapshot_owner", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.save(update_fields=["silver"])
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()

    snapshots = build_guest_battle_snapshots([guest], include_identity=True)
    assert snapshots[0]["manor_id"] == manor.pk

    legacy_snapshot = dict(snapshots[0])
    legacy_snapshot.pop("manor_id")
    guest.delete()

    snapshot_guest = build_guest_snapshot_proxies([legacy_snapshot], include_guest_identity=True)[0]
    report = simulate_report(
        manor,
        seed=7,
        troop_loadout={},
        fill_default_troops=False,
        attacker_guests=[snapshot_guest],
        auto_reward=False,
        send_message=False,
        apply_damage=False,
        use_lock=False,
    )

    assert isinstance(report, BattleReport)


@pytest.mark.django_db
def test_simulate_report_rewards_on_victory(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="champion", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.save()
    _recruit_frontline(manor, draws=4)
    # 设置高属性并确保门客满血
    for guest in manor.guests.all():
        guest.level = 50
        guest.attack_bonus = 800
        guest.defense_bonus = 800
        guest.intellect = 800
        guest.force = 800
        guest.defense_stat = 300
        guest.current_hp = guest.max_hp  # 确保满血
        guest.save()
    before = manor.resource_dict()
    # 4名门客可带800人，配置合理的兵力
    troop_loadout = {"dao_jie": 150, "qiang_ling": 150, "archer": 150, "fist_master": 150, "jian_shi": 150}
    report = simulate_report(
        manor, seed=1, max_squad=getattr(manor, "max_squad_size", None), troop_loadout=troop_loadout
    )
    assert report.winner == "attacker"
    assert report.drops
    manor.refresh_from_db()
    after = manor.resource_dict()
    for resource, amount in report.drops.items():
        assert after[resource] == before[resource] + amount


@pytest.mark.django_db
def test_simulate_report_requires_idle_guests(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="busy", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 3000
    manor.save()
    _recruit_frontline(manor, draws=2)
    manor.guests.update(status=GuestStatus.WORKING)

    with pytest.raises(ValueError) as exc:
        simulate_report(manor, seed=5)

    assert "空闲" in str(exc.value) or "重伤" in str(exc.value)


@pytest.mark.django_db
def test_defeated_guest_becomes_injured(game_data, django_user_model):
    """阵亡的门客变为重伤状态"""
    user = django_user_model.objects.create_user(username="defeated", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.save()
    _recruit_frontline(manor, draws=3)
    # 设置门客为低血量，战斗中容易阵亡
    for guest in manor.guests.all():
        guest.current_hp = 1
        guest.status = GuestStatus.IDLE
        guest.save()
    troop_loadout = {"dao_jie": 100, "qiang_ling": 100, "archer": 100, "fist_master": 100, "jian_shi": 100}
    defender_setup = {"troop_loadout": {k: 5000 for k in troop_loadout}}
    report = simulate_report(manor, seed=99, troop_loadout=troop_loadout, defender_setup=defender_setup)
    assert report.winner == "defender"
    # 检查是否有门客变为重伤
    manor.refresh_from_db()
    injured_guests = manor.guests.filter(status=GuestStatus.INJURED)
    assert injured_guests.exists()
    # 由于初始HP=1，很可能有门客阵亡
    # 无论输赢，只要有人阵亡就应该变为重伤
    for guest in manor.guests.all():
        guest.refresh_from_db()
        if guest.status == GuestStatus.INJURED:
            assert guest.current_hp == 1  # 重伤门客HP保持为1


@pytest.mark.django_db
def test_injured_guest_cannot_deploy(django_user_model):
    """重伤门客无法出征"""
    user = django_user_model.objects.create_user(username="injured", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.save()
    _recruit_frontline(manor, draws=3)
    # 将所有门客设为重伤状态
    for guest in manor.guests.all():
        guest.status = GuestStatus.INJURED
        guest.current_hp = 1
        guest.save()
    troop_loadout = {"dao_jie": 100, "qiang_ling": 100, "archer": 100, "fist_master": 100, "jian_shi": 100}
    # 重伤门客无法出征，应抛出异常
    with pytest.raises(ValueError) as exc:
        simulate_report(manor, seed=1, troop_loadout=troop_loadout)
    assert "重伤" in str(exc.value)


@pytest.mark.django_db
def test_lock_guests_for_battle_marks_and_releases_defender_guests(game_data, django_user_model):
    from battle.services import lock_guests_for_battle

    attacker_user = django_user_model.objects.create_user(username="battle_lock_a", password="pass123")
    defender_user = django_user_model.objects.create_user(username="battle_lock_b", password="pass123")
    attacker_manor = ensure_manor(attacker_user)
    defender_manor = ensure_manor(defender_user)
    _recruit_frontline(attacker_manor, draws=1)
    _recruit_frontline(defender_manor, draws=1)

    attacker_guest = attacker_manor.guests.first()
    defender_guest = defender_manor.guests.first()

    with lock_guests_for_battle([attacker_guest], manor=attacker_manor, other_guests=[defender_guest]):
        attacker_guest.refresh_from_db(fields=["status"])
        defender_guest.refresh_from_db(fields=["status"])
        assert attacker_guest.status == GuestStatus.DEPLOYED
        assert defender_guest.status == GuestStatus.DEPLOYED

    attacker_guest.refresh_from_db(fields=["status"])
    defender_guest.refresh_from_db(fields=["status"])
    assert attacker_guest.status == GuestStatus.IDLE
    assert defender_guest.status == GuestStatus.IDLE


@pytest.mark.django_db
def test_lock_guests_for_battle_releases_transaction_before_battle_body(game_data, django_user_model, monkeypatch):
    import battle.services as battle_services
    from battle.services import lock_guests_for_battle

    user = django_user_model.objects.create_user(username="battle_lock_txn", password="pass123")
    manor = ensure_manor(user)
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()

    atomic_depth = {"value": 0}
    real_atomic = battle_services.transaction.atomic

    class _RecordingAtomic:
        def __call__(self, *args, **kwargs):
            context = real_atomic(*args, **kwargs)

            class _WrappedContext:
                def __enter__(self_inner):
                    atomic_depth["value"] += 1
                    return context.__enter__()

                def __exit__(self_inner, exc_type, exc, tb):
                    try:
                        return context.__exit__(exc_type, exc, tb)
                    finally:
                        atomic_depth["value"] -= 1

            return _WrappedContext()

    monkeypatch.setattr(battle_services.transaction, "atomic", _RecordingAtomic())
    with lock_guests_for_battle([guest], manor=manor):
        assert atomic_depth["value"] == 0


@pytest.mark.django_db
def test_lock_guests_for_battle_recovers_orphaned_deployed_guest(game_data, django_user_model):
    from battle.services import lock_guests_for_battle

    user = django_user_model.objects.create_user(username="battle_lock_orphaned", password="pass123")
    manor = ensure_manor(user)
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    with lock_guests_for_battle([guest], manor=manor):
        guest.refresh_from_db(fields=["status"])
        assert guest.status == GuestStatus.DEPLOYED

    guest.refresh_from_db(fields=["status"])
    assert guest.status == GuestStatus.IDLE


@pytest.mark.django_db
def test_recover_orphaned_deployed_guests_resets_untracked_guest(game_data, django_user_model, caplog):
    user = django_user_model.objects.create_user(username="battle_recover_orphaned", password="pass123")
    manor = ensure_manor(user)
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    caplog.set_level("WARNING", logger="battle.services")
    recovered = recover_orphaned_deployed_guests(guest_ids=[guest.id])

    guest.refresh_from_db(fields=["status"])
    assert recovered == 1
    assert guest.status == GuestStatus.IDLE
    assert any(
        "Recovered orphaned deployed guests before battle reuse" in record.getMessage() for record in caplog.records
    )
    assert any(BATTLE_ORPHANED_DEPLOYED_RECOVERY_COUNTER in record.getMessage() for record in caplog.records)


@pytest.mark.django_db
def test_recover_orphaned_deployed_guests_records_monitoring_signal(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="battle_recover_monitor", password="pass123")
    manor = ensure_manor(user)
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    calls: list[str] = []
    monkeypatch.setattr("battle.services.increment_degraded_counter", lambda component: calls.append(component))

    recovered = recover_orphaned_deployed_guests(guest_ids=[guest.id])

    assert recovered == 1
    assert calls == [BATTLE_ORPHANED_DEPLOYED_RECOVERY_COUNTER]


@pytest.mark.django_db
@pytest.mark.parametrize("deployment_kind", ["mission", "raid", "arena"])
def test_recover_orphaned_deployed_guests_keeps_active_deployments(
    game_data,
    django_user_model,
    deployment_kind,
):
    user = django_user_model.objects.create_user(
        username=f"battle_recover_active_{deployment_kind}", password="pass123"
    )
    manor = ensure_manor(user)
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    if deployment_kind == "mission":
        mission = MissionTemplate.objects.create(key="battle_recover_active_mission", name="Battle Recover Mission")
        run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE)
        run.guests.add(guest)
    elif deployment_kind == "raid":
        defender_user = django_user_model.objects.create_user(
            username=f"battle_recover_active_defender_{deployment_kind}",
            password="pass123",
        )
        defender = ensure_manor(defender_user)
        run = RaidRun.objects.create(attacker=manor, defender=defender, status=RaidRun.Status.MARCHING)
        run.guests.add(guest)
    else:
        tournament = ArenaTournament.objects.create(status=ArenaTournament.Status.RECRUITING, player_limit=8)
        entry = ArenaEntry.objects.create(
            tournament=tournament,
            manor=manor,
            status=ArenaEntry.Status.REGISTERED,
        )
        ArenaEntryGuest.objects.create(entry=entry, guest=guest, snapshot={"guest_id": guest.id})

    recovered = recover_orphaned_deployed_guests(guest_ids=[guest.id])

    guest.refresh_from_db(fields=["status"])
    assert recovered == 0
    assert guest.status == GuestStatus.DEPLOYED


@pytest.mark.django_db
def test_heal_guest_cures_injury(django_user_model):
    """药品治疗可解除重伤状态（HP>=30%时）"""

    user = django_user_model.objects.create_user(username="healer", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 3000
    manor.save()
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()
    # 设置为重伤状态
    guest.status = GuestStatus.INJURED
    guest.current_hp = 1
    guest.save()

    max_hp = guest.max_hp
    threshold_hp = int(max_hp * INJURY_RECOVERY_THRESHOLD)

    # 治疗量不足，仍处于重伤
    heal_amount = threshold_hp - 10
    if heal_amount > 0:
        result = heal_guest(guest, heal_amount)
        guest.refresh_from_db()
        assert guest.status == GuestStatus.INJURED
        assert not result["injury_cured"]

    # 治疗到30%以上，解除重伤
    guest.current_hp = 1
    guest.status = GuestStatus.INJURED
    guest.save()
    heal_amount = threshold_hp + 10
    result = heal_guest(guest, heal_amount)
    guest.refresh_from_db()
    assert guest.status == GuestStatus.IDLE
    assert result["injury_cured"]


@pytest.mark.django_db
def test_heal_guest_rejects_busy_non_injured_status(django_user_model):
    user = django_user_model.objects.create_user(username="busy_healer", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 3000
    manor.save(update_fields=["silver"])
    _recruit_frontline(manor, draws=1)
    guest = manor.guests.first()
    guest.status = GuestStatus.WORKING
    guest.current_hp = max(1, guest.max_hp - 100)
    guest.save(update_fields=["status", "current_hp"])

    with pytest.raises(GuestNotIdleError):
        heal_guest(guest, 50)


def test_extract_defender_tech_profile_tolerates_invalid_technology_config():
    levels, guest_level, bonuses, skills = _extract_defender_tech_profile({"technology": "bad-config"})
    assert levels == {}
    assert guest_level == 50
    assert bonuses == {}
    assert skills is None

    levels, guest_level, bonuses, skills = _extract_defender_tech_profile(
        {"technology": {"guest_level": "bad", "guest_skills": "not-a-list"}}
    )
    assert levels == {}
    assert guest_level == 50
    assert skills is None


def test_build_defender_guest_and_loadout_tolerates_invalid_defender_setup(monkeypatch):
    monkeypatch.setattr("battle.services.generate_ai_loadout", lambda _rng: {"archer": 1})
    monkeypatch.setattr("battle.services.build_ai_guests", lambda _rng: ["ai-guest"])
    monkeypatch.setattr(
        "battle.services.build_guest_combatants",
        lambda _guests, **_kwargs: ["combatant"],
    )

    guests, loadout = _build_defender_guest_and_loadout(
        defender_guests=None,
        defender_setup="bad-config",
        defender_limit=3,
        fill_default_troops=True,
        rng=random.Random(1),
        now=timezone.now(),
        defender_guest_level=50,
        defender_guest_bonuses={},
        defender_guest_skills=None,
    )
    assert guests == ["combatant"]
    assert loadout == {"archer": 1}


def test_build_defender_guest_and_loadout_sanitizes_invalid_nested_fields(monkeypatch):
    state = {}

    monkeypatch.setattr("battle.services.generate_ai_loadout", lambda _rng: {"archer": 1})
    monkeypatch.setattr("battle.services.build_ai_guests", lambda _rng: ["ai-guest"])
    monkeypatch.setattr(
        "battle.services.build_named_ai_guests",
        lambda keys, level: state.update({"keys": keys, "level": level}) or ["named-ai"],
    )
    monkeypatch.setattr(
        "battle.services.build_guest_combatants",
        lambda _guests, **_kwargs: ["combatant"],
    )
    monkeypatch.setattr(
        "battle.services.normalize_troop_loadout",
        lambda loadout, **_kwargs: state.update({"loadout_arg": loadout}) or {"safe": 1},
    )

    guests, loadout = _build_defender_guest_and_loadout(
        defender_guests=None,
        defender_setup={"guest_keys": "bad-guests", "troop_loadout": "bad-loadout"},
        defender_limit=3,
        fill_default_troops=True,
        rng=random.Random(1),
        now=timezone.now(),
        defender_guest_level=50,
        defender_guest_bonuses={},
        defender_guest_skills=None,
    )
    assert guests == ["combatant"]
    assert loadout == {"safe": 1}
    assert state["keys"] == []
    assert state["loadout_arg"] is None
