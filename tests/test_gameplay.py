from datetime import timedelta

import pytest
from django.utils import timezone

from gameplay.models import MissionTemplate
from gameplay.services.manor import ensure_manor, refresh_manor_state, start_upgrade
from gameplay.services.missions import launch_mission, refresh_mission_runs
from guests.models import GuestStatus
from guests.services import finalize_candidate, recruit_guest


@pytest.mark.django_db
def test_resource_production_increase(django_user_model):
    user = django_user_model.objects.create_user(username="player1", password="pass12345")
    manor = ensure_manor(user)
    before_silver = manor.silver
    manor.resource_updated_at = timezone.now() - timedelta(hours=2)
    manor.save()
    refresh_manor_state(manor)
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


@pytest.mark.django_db(transaction=True)
def test_mission_launch_and_return(mission_templates, manor_with_troops):
    """测试任务发起和护院归还"""
    mission = MissionTemplate.objects.get(key="huashan_lunjian")
    manor = manor_with_troops

    # Recruit frontline guests
    from guests.models import RecruitmentPool

    pool = RecruitmentPool.objects.get(key="tongshi")
    for seed in range(3):
        candidates = recruit_guest(manor, pool, seed=seed)
        finalize_candidate(candidates[0])
    guests = list(manor.guests.all()[:3])

    # 验证出征前护院数量
    from gameplay.models import PlayerTroop
    from battle.models import TroopTemplate

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
def test_mission_launch_with_invalid_troop_type(mission_templates, manor_with_troops):
    """测试出征包含不存在的护院类型时抛出异常，不会创建新护院"""
    from gameplay.models import PlayerTroop
    from battle.models import TroopTemplate
    from guests.models import RecruitmentPool, Guest

    mission = MissionTemplate.objects.get(key="huashan_lunjian")
    manor = manor_with_troops

    # 创建测试门客（直接创建，不需要通过招募系统）
    from guests.models import GuestTemplate
    template = GuestTemplate.objects.first()
    if template:
        guest = Guest.objects.create(
            manor=manor,
            template=template,
            level=50,
            status=GuestStatus.IDLE
        )
    else:
        # 如果没有模板，跳过此测试
        pytest.skip("No guest template available")

    # 确认不存在某个护院类型
    fake_troop_key = "nonexistent_troop_xxx"
    assert not PlayerTroop.objects.filter(
        manor=manor,
        troop_template__key=fake_troop_key
    ).exists()

    # 尝试出征包含不存在的护院类型
    with pytest.raises(ValueError) as exc:
        launch_mission(manor, mission, [guest.id], {fake_troop_key: 100})

    assert "不存在的类型" in str(exc.value)

    # 确保没有创建该护院记录
    assert not PlayerTroop.objects.filter(
        manor=manor,
        troop_template__key=fake_troop_key
    ).exists()

