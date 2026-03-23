from datetime import timedelta

import pytest
from django.utils import timezone
from django_redis.exceptions import ConnectionInterrupted

import gameplay.services.manor.core as manor_service
from core.exceptions import (
    MissionCannotRetreatError,
    MissionSquadSizeExceededError,
    MissionTroopLoadoutError,
    TroopLoadoutError,
)
from gameplay.constants import MAX_CONCURRENT_BUILDING_UPGRADES
from gameplay.models import MissionRun, MissionTemplate, RaidRun, ScoutRecord
from gameplay.services.manor.core import ensure_manor, refresh_manor_state, start_upgrade
from gameplay.services.missions import launch_mission, refresh_mission_runs, request_retreat
from gameplay.services.missions_impl import loadout as mission_loadout_service
from gameplay.services.missions_impl.launch_command import (
    _resolve_base_travel_time,
    _resolve_max_squad_size,
    prepare_launch_inputs,
)
from gameplay.utils.resource_calculator import calculate_travel_time, normalize_mission_loadout
from guests.models import GuestStatus
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate


@pytest.mark.django_db
def test_resource_production_increase(django_user_model):
    user = django_user_model.objects.create_user(username="player1", password="pass12345")
    manor = ensure_manor(user)
    before_silver = manor.silver
    manor.resource_updated_at = timezone.now() - timedelta(hours=2)
    manor.save()
    refresh_manor_state(manor, include_activity_refresh=True)
    manor.refresh_from_db()
    assert manor.silver >= before_silver


@pytest.mark.django_db
def test_upgrade_consumes_resources(django_user_model):
    user = django_user_model.objects.create_user(username="player2", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.first()
    manor.grain = manor.silver = 50000
    manor.save()
    start_upgrade(building)
    manor.refresh_from_db()
    building.refresh_from_db()
    assert building.is_upgrading is True
    assert manor.silver < 50000


@pytest.mark.django_db
def test_start_upgrade_finalizes_due_upgrades_before_slot_check(django_user_model):
    user = django_user_model.objects.create_user(username="player_upgrade_due_finalize", password="pass12345")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    buildings = list(manor.buildings.order_by("id")[: MAX_CONCURRENT_BUILDING_UPGRADES + 1])
    if len(buildings) < MAX_CONCURRENT_BUILDING_UPGRADES + 1:
        pytest.skip("Not enough buildings to verify concurrent upgrade slot reuse")

    now = timezone.now()
    stale_buildings = buildings[:MAX_CONCURRENT_BUILDING_UPGRADES]
    target_building = buildings[MAX_CONCURRENT_BUILDING_UPGRADES]
    for stale in stale_buildings:
        stale.is_upgrading = True
        stale.upgrade_complete_at = now - timedelta(seconds=1)
        stale.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    start_upgrade(target_building)

    target_building.refresh_from_db()
    assert target_building.is_upgrading is True
    assert target_building.upgrade_complete_at is not None
    for stale in stale_buildings:
        stale.refresh_from_db()
        assert stale.is_upgrading is False
        assert stale.upgrade_complete_at is None


@pytest.mark.django_db(transaction=True)
def test_mission_launch_and_return(game_data, mission_templates, manor_with_troops):
    """测试任务发起和护院归还"""
    mission = MissionTemplate.objects.filter(guest_only=False, is_defense=False).first()
    if not mission:
        pytest.skip("No mission available that allows troops")
    manor = manor_with_troops
    manor.silver = max(int(manor.silver or 0), 5_000)
    manor.save(update_fields=["silver"])

    # Recruit frontline guests
    from guests.models import RecruitmentPool

    pool = RecruitmentPool.objects.get(key="cunmu")
    for seed in range(3):
        candidates = recruit_guest(manor, pool, seed=seed)
        finalize_candidate(candidates[0])
    guests = list(manor.guests.all()[:3])

    # 验证出征前护院数量
    from battle.models import TroopTemplate
    from gameplay.models import PlayerTroop

    archer_template = TroopTemplate.objects.get(key="archer")
    troop_before = PlayerTroop.objects.get(manor=manor, troop_template=archer_template)
    initial_count = troop_before.count
    assert initial_count >= 100

    # 出征消耗 100 archer
    run = launch_mission(manor, mission, [g.id for g in guests], {"archer": 100})
    assert run.battle_report is not None
    assert run.mission == mission
    assert run.guests.count() == len(guests)
    for guest in guests:
        guest.refresh_from_db()
        assert guest.status == GuestStatus.DEPLOYED

    # 验证出征后护院已扣除
    troop_before.refresh_from_db()
    assert troop_before.count == initial_count - 100

    # fast-forward return
    run.return_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["return_at"])
    refresh_mission_runs(manor)

    # 验证任务完成后门客状态（IDLE 或 INJURED 都是正常结果）
    for guest in guests:
        guest.refresh_from_db()
        # 门客可能重伤（INJURED），也可能正常（IDLE）
        assert guest.status in [GuestStatus.IDLE, GuestStatus.INJURED]

    troop_before.refresh_from_db()
    # 护院数量应该 >=出征后数量（可能有伤亡）
    assert troop_before.count >= initial_count - 100


@pytest.mark.django_db(transaction=True)
def test_mission_launch_with_invalid_troop_type(game_data, mission_templates, manor_with_troops):
    """测试出征包含不存在的护院类型时抛出异常，不会创建新护院"""
    from gameplay.models import PlayerTroop
    from guests.models import Guest

    mission = MissionTemplate.objects.filter(guest_only=False, is_defense=False).first()
    if not mission:
        pytest.skip("No mission available that allows troops")
    manor = manor_with_troops

    # 创建测试门客（直接创建，不需要通过招募系统）
    from guests.models import GuestTemplate

    template = GuestTemplate.objects.first()
    if template:
        guest = Guest.objects.create(manor=manor, template=template, level=50, status=GuestStatus.IDLE)
    else:
        # 如果没有模板，跳过此测试
        pytest.skip("No guest template available")

    # 确认不存在某个护院类型
    fake_troop_key = "nonexistent_troop_xxx"
    assert not PlayerTroop.objects.filter(manor=manor, troop_template__key=fake_troop_key).exists()

    # 尝试出征包含不存在的护院类型
    with pytest.raises(MissionTroopLoadoutError) as exc:
        launch_mission(manor, mission, [guest.id], {fake_troop_key: 100})

    assert "不存在的类型" in str(exc.value)

    # 确保没有创建该护院记录
    assert not PlayerTroop.objects.filter(manor=manor, troop_template__key=fake_troop_key).exists()


def test_normalize_mission_loadout_rejects_unknown_troop_keys():
    with pytest.raises(TroopLoadoutError, match="不存在的类型"):
        normalize_mission_loadout(
            {"nonexistent_troop_xxx": 1},
            troop_templates={"archer": {"label": "弓手"}},
        )


def test_normalize_mission_loadout_ignores_unknown_troop_keys_with_invalid_quantity_shape():
    loadout = normalize_mission_loadout(
        {"nonexistent_troop_xxx": "not-a-number"},
        troop_templates={"archer": {"label": "弓手"}},
    )

    assert loadout == {"archer": 0}


def test_normalize_mission_loadout_rejects_invalid_payload_shape():
    with pytest.raises(AssertionError, match="invalid mission troop loadout payload"):
        normalize_mission_loadout(
            ["archer"],
            troop_templates={"archer": {"label": "弓手"}},
        )


def test_mission_loadout_service_rejects_missing_troop_templates(monkeypatch):
    monkeypatch.setattr("battle.troops.load_troop_templates", lambda: {})

    with pytest.raises(AssertionError, match="mission troop templates must not be empty"):
        mission_loadout_service.normalize_mission_loadout({"archer": 1})


def test_mission_travel_time_rejects_missing_troop_templates_for_non_empty_loadout(monkeypatch):
    monkeypatch.setattr("battle.troops.load_troop_templates", lambda: {})

    with pytest.raises(AssertionError, match="mission troop templates must not be empty"):
        mission_loadout_service.travel_time_seconds(60, guests=[], troop_loadout={"archer": 1})


def test_calculate_travel_time_rejects_invalid_loadout_shape():
    with pytest.raises(AssertionError, match="invalid mission troop loadout payload"):
        calculate_travel_time(60, guests=[], troop_loadout=["archer"], troop_templates={"archer": {"speed_bonus": 1}})


def test_resolve_max_squad_size_rejects_invalid_bool():
    with pytest.raises(AssertionError, match="invalid mission max_squad_size"):
        _resolve_max_squad_size(type("_Manor", (), {"max_squad_size": True})())


def test_resolve_max_squad_size_rejects_negative_value():
    with pytest.raises(AssertionError, match="invalid mission max_squad_size"):
        _resolve_max_squad_size(type("_Manor", (), {"max_squad_size": -1})())


def test_resolve_base_travel_time_rejects_invalid_bool():
    with pytest.raises(AssertionError, match="invalid mission base_travel_time"):
        _resolve_base_travel_time(type("_Mission", (), {"base_travel_time": True})())


def test_resolve_base_travel_time_rejects_non_positive_value():
    with pytest.raises(AssertionError, match="invalid mission base_travel_time"):
        _resolve_base_travel_time(type("_Mission", (), {"base_travel_time": 0})())


def test_prepare_launch_inputs_rejects_defense_guest_ids():
    mission = type("_Mission", (), {"is_defense": True, "base_travel_time": 60})()

    with pytest.raises(AssertionError, match="defense mission guest_ids must be empty"):
        prepare_launch_inputs(
            object(), mission, [1], {}, scale_duration=lambda seconds, minimum=1: max(minimum, seconds)
        )


def test_prepare_launch_inputs_rejects_defense_troop_loadout():
    mission = type("_Mission", (), {"is_defense": True, "base_travel_time": 60})()

    with pytest.raises(AssertionError, match="defense mission troop_loadout must be empty"):
        prepare_launch_inputs(
            object(),
            mission,
            [],
            {"archer": 1},
            scale_duration=lambda seconds, minimum=1: max(minimum, seconds),
        )


@pytest.mark.django_db(transaction=True)
def test_mission_launch_with_insufficient_troops_wraps_shared_loadout_error(
    game_data, mission_templates, manor_with_troops
):
    """共享护院扣减错误应被包装成 MissionTroopLoadoutError。"""
    from battle.models import TroopTemplate
    from gameplay.models import PlayerTroop
    from guests.models import Guest, GuestTemplate

    mission = MissionTemplate.objects.filter(guest_only=False, is_defense=False).first()
    if not mission:
        pytest.skip("No mission available that allows troops")
    manor = manor_with_troops
    template = GuestTemplate.objects.first()
    if template is None:
        pytest.skip("No guest template available")

    guest = Guest.objects.create(manor=manor, template=template, level=50, status=GuestStatus.IDLE)
    troop_template = TroopTemplate.objects.create(
        key="mission_insufficient_guard",
        name="任务测试护院",
        description="",
        base_attack=1,
        base_defense=1,
        base_hp=1,
        speed_bonus=0,
        priority=9999,
        default_count=0,
    )
    PlayerTroop.objects.create(manor=manor, troop_template=troop_template, count=1)

    with pytest.raises(MissionTroopLoadoutError) as exc:
        launch_mission(manor, mission, [guest.id], {troop_template.key: 2})

    assert "数量不足" in str(exc.value)


@pytest.mark.django_db(transaction=True)
def test_mission_launch_rejects_when_guest_count_exceeds_max_squad(game_data, mission_templates, manor_with_troops):
    """服务层应拒绝超出上阵人数上限的任务出征请求。"""
    from guests.models import Guest, GuestTemplate

    mission = MissionTemplate.objects.filter(is_defense=False).order_by("-guest_only", "id").first()
    if not mission:
        pytest.skip("No offense mission available")
    manor = manor_with_troops
    template = GuestTemplate.objects.first()
    if template is None:
        pytest.skip("No guest template available")

    max_squad_size = getattr(manor, "max_squad_size", 0)
    if max_squad_size <= 0:
        pytest.skip("Invalid manor max_squad_size")

    guests = [
        Guest.objects.create(
            manor=manor,
            template=template,
            level=10,
            status=GuestStatus.IDLE,
            custom_name=f"mission_limit_guest_{idx}",
        )
        for idx in range(max_squad_size + 1)
    ]

    with pytest.raises(MissionSquadSizeExceededError) as exc:
        launch_mission(manor, mission, [guest.id for guest in guests], {})
    assert f"最多只能派出 {max_squad_size} 名门客出征" in str(exc.value)

    for guest in guests:
        guest.refresh_from_db()
        assert guest.status == GuestStatus.IDLE


@pytest.mark.django_db(transaction=True)
def test_request_retreat_raises_mission_cannot_retreat_when_already_retreating(django_user_model, monkeypatch):
    import gameplay.services.missions_impl.execution as mission_execution

    user = django_user_model.objects.create_user(username="player_mission_retreating", password="pass12345")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="mission_retreating_case", name="撤退测试任务", is_defense=False)
    run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE, travel_time=300)

    monkeypatch.setattr(mission_execution, "schedule_mission_completion", lambda *_args, **_kwargs: None)
    request_retreat(run)

    with pytest.raises(MissionCannotRetreatError, match="任务已在撤退中"):
        request_retreat(run)


@pytest.mark.django_db(transaction=True)
def test_request_retreat_rejects_future_started_at_contract(django_user_model, monkeypatch):
    import gameplay.services.missions_impl.execution as mission_execution

    user = django_user_model.objects.create_user(username="player_mission_retreat_future", password="pass12345")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(key="mission_retreat_future_case", name="未来撤退测试", is_defense=False)
    run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE, travel_time=300)
    future_started_at = timezone.now() + timedelta(seconds=10)
    MissionRun.objects.filter(pk=run.pk).update(started_at=future_started_at)
    run.refresh_from_db()

    monkeypatch.setattr(mission_execution, "schedule_mission_completion", lambda *_args, **_kwargs: None)

    with pytest.raises(AssertionError, match="started_at cannot be in the future"):
        request_retreat(run)


@pytest.mark.django_db(transaction=True)
def test_request_retreat_immediate_retreat_preserves_minimum_return_time(django_user_model, monkeypatch):
    import gameplay.services.missions_impl.execution as mission_execution

    user = django_user_model.objects.create_user(username="player_mission_retreat_immediate", password="pass12345")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.create(
        key="mission_retreat_immediate_case", name="立即撤退测试", is_defense=False
    )
    run = MissionRun.objects.create(manor=manor, mission=mission, status=MissionRun.Status.ACTIVE, travel_time=300)
    started_at = timezone.now()
    MissionRun.objects.filter(pk=run.pk).update(started_at=started_at)
    run.refresh_from_db()

    monkeypatch.setattr(mission_execution, "schedule_mission_completion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("gameplay.services.missions_impl.retreat_command.timezone.now", lambda: started_at)

    request_retreat(run)

    run.refresh_from_db()
    assert run.is_retreating is True
    assert run.return_at == started_at + timedelta(seconds=1)


@pytest.mark.django_db
def test_refresh_manor_state_defaults_to_read_projection_only(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_projection_only", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 0

    calls = {"finalize": 0, "resource": 0, "mission": 0, "scout": 0, "raid": 0}
    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor, prefer_async=False: calls.__setitem__("mission", calls["mission"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_scout_records",
        lambda _manor, prefer_async=False: calls.__setitem__("scout", calls["scout"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_raid_runs",
        lambda _manor, prefer_async=False: calls.__setitem__("raid", calls["raid"] + 1),
    )

    refresh_manor_state(manor)

    assert calls == {"finalize": 1, "resource": 1, "mission": 0, "scout": 0, "raid": 0}


@pytest.mark.django_db
def test_refresh_manor_state_local_fallback_throttles_when_cache_unavailable(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_fallback", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5

    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    monkeypatch.setattr(
        manor_service.cache, "add", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache down"))
    )

    calls = {"finalize": 0, "resource": 0, "mission": 0}

    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    refresh_manor_state(manor, include_activity_refresh=True)

    assert calls == {"finalize": 2, "resource": 1, "mission": 1}


@pytest.mark.django_db
def test_refresh_manor_state_local_fallback_allows_after_interval(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_interval", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5

    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    monkeypatch.setattr(
        manor_service.cache, "add", lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache down"))
    )

    monotonic_values = iter([100.0, 102.0, 106.1])
    monkeypatch.setattr(manor_service.time, "monotonic", lambda: next(monotonic_values))

    calls = {"finalize": 0, "resource": 0, "mission": 0}

    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    refresh_manor_state(manor, include_activity_refresh=True)
    refresh_manor_state(manor, include_activity_refresh=True)

    assert calls == {"finalize": 3, "resource": 2, "mission": 2}


@pytest.mark.django_db
def test_refresh_manor_state_runtime_marker_cache_error_bubbles_up(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_runtime_marker", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5
    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    monkeypatch.setattr(
        manor_service.cache, "add", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cache down"))
    )

    with pytest.raises(RuntimeError, match="cache down"):
        refresh_manor_state(manor, include_activity_refresh=True)


@pytest.mark.django_db
def test_refresh_manor_state_bypasses_cache_throttle_when_upgrade_due(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_due_upgrade", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.first()
    assert building is not None
    building.is_upgrading = True
    building.upgrade_complete_at = timezone.now() - timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5
    monkeypatch.setattr(manor_service.cache, "add", lambda *args, **kwargs: False)

    calls = {"finalize": 0, "resource": 0, "mission": 0}
    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    assert calls == {"finalize": 1, "resource": 0, "mission": 0}


@pytest.mark.django_db
def test_refresh_manor_state_still_throttles_when_cache_hit_and_no_due_work(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_no_due", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5
    monkeypatch.setattr(manor_service.cache, "add", lambda *args, **kwargs: False)

    calls = {"finalize": 0, "resource": 0, "mission": 0}
    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    assert calls == {"finalize": 1, "resource": 0, "mission": 0}


@pytest.mark.django_db
def test_refresh_manor_state_falls_back_to_local_throttle_when_cache_backend_unavailable(
    django_user_model, settings, monkeypatch
):
    user = django_user_model.objects.create_user(username="player_refresh_cache_unavailable", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5
    monkeypatch.setattr(
        manor_service.cache,
        "add",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionInterrupted("redis unavailable")),
    )

    calls = {"finalize": 0, "resource": 0, "mission": 0, "scout": 0, "raid": 0}
    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_scout_records",
        lambda _manor: calls.__setitem__("scout", calls["scout"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_raid_runs",
        lambda _manor: calls.__setitem__("raid", calls["raid"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    refresh_manor_state(manor, include_activity_refresh=True)

    assert calls == {"finalize": 2, "resource": 1, "mission": 1, "scout": 1, "raid": 1}


@pytest.mark.django_db
def test_refresh_manor_state_bypasses_cache_throttle_when_scout_due(django_user_model, settings, monkeypatch):
    attacker = django_user_model.objects.create_user(username="player_refresh_due_scout", password="pass12345")
    defender = django_user_model.objects.create_user(username="player_refresh_due_scout_target", password="pass12345")
    manor = ensure_manor(attacker)
    target_manor = ensure_manor(defender)

    ScoutRecord.objects.create(
        attacker=manor,
        defender=target_manor,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        complete_at=timezone.now() - timedelta(seconds=1),
    )

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5
    monkeypatch.setattr(manor_service.cache, "add", lambda *args, **kwargs: False)

    calls = {"finalize": 0, "resource": 0, "mission": 0, "scout": 0, "raid": 0}
    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_scout_records",
        lambda _manor: calls.__setitem__("scout", calls["scout"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_raid_runs",
        lambda _manor: calls.__setitem__("raid", calls["raid"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    assert calls == {"finalize": 1, "resource": 1, "mission": 1, "scout": 1, "raid": 1}


@pytest.mark.django_db
def test_refresh_manor_state_bypasses_cache_throttle_when_raid_due(django_user_model, settings, monkeypatch):
    attacker = django_user_model.objects.create_user(username="player_refresh_due_raid", password="pass12345")
    defender = django_user_model.objects.create_user(username="player_refresh_due_raid_target", password="pass12345")
    manor = ensure_manor(attacker)
    target_manor = ensure_manor(defender)

    RaidRun.objects.create(
        attacker=manor,
        defender=target_manor,
        status=RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=timezone.now() - timedelta(seconds=1),
    )

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 5
    monkeypatch.setattr(manor_service.cache, "add", lambda *args, **kwargs: False)

    calls = {"finalize": 0, "resource": 0, "mission": 0, "scout": 0, "raid": 0}
    monkeypatch.setattr(
        manor_service, "finalize_upgrades", lambda _manor: calls.__setitem__("finalize", calls["finalize"] + 1)
    )
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor: calls.__setitem__("mission", calls["mission"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_scout_records",
        lambda _manor: calls.__setitem__("scout", calls["scout"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_raid_runs",
        lambda _manor: calls.__setitem__("raid", calls["raid"] + 1),
    )

    refresh_manor_state(manor, include_activity_refresh=True)
    assert calls == {"finalize": 1, "resource": 1, "mission": 1, "scout": 1, "raid": 1}


@pytest.mark.django_db
def test_refresh_manor_state_propagates_prefer_async_to_all_refresh_hooks(django_user_model, settings, monkeypatch):
    user = django_user_model.objects.create_user(username="player_refresh_async_hooks", password="pass12345")
    manor = ensure_manor(user)

    settings.MANOR_STATE_REFRESH_MIN_INTERVAL_SECONDS = 0

    calls = {"resource": 0, "mission": [], "scout": [], "raid": []}
    monkeypatch.setattr(manor_service, "finalize_upgrades", lambda _manor: None)
    monkeypatch.setattr(
        "gameplay.services.resources.sync_resource_production",
        lambda _manor: calls.__setitem__("resource", calls["resource"] + 1),
    )
    monkeypatch.setattr(
        "gameplay.services.missions.refresh_mission_runs",
        lambda _manor, prefer_async=False: calls["mission"].append(prefer_async),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_scout_records",
        lambda _manor, prefer_async=False: calls["scout"].append(prefer_async),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.refresh_raid_runs",
        lambda _manor, prefer_async=False: calls["raid"].append(prefer_async),
    )

    refresh_manor_state(manor, prefer_async=True, include_activity_refresh=True)
    assert calls == {"resource": 1, "mission": [True], "scout": [True], "raid": [True]}
