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


@pytest.mark.django_db
def test_mission_launch_and_return(django_user_model):
    user = django_user_model.objects.create_user(username="player3", password="pass12345")
    manor = ensure_manor(user)
    mission = MissionTemplate.objects.get(key="huashan_lunjian")
    # Recruit frontline guests
    from guests.models import RecruitmentPool

    pool = RecruitmentPool.objects.get(key="tongshi")
    for seed in range(3):
        candidates = recruit_guest(manor, pool, seed=seed)
        finalize_candidate(candidates[0])
    guests = list(manor.guests.all()[:3])
    run = launch_mission(manor, mission, [g.id for g in guests], {"archer": 100})
    assert run.battle_report is not None
    assert run.mission == mission
    assert run.guests.count() == len(guests)
    for guest in guests:
        guest.refresh_from_db()
        assert guest.status == GuestStatus.DEPLOYED
    # fast-forward return
    run.return_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["return_at"])
    refresh_mission_runs(manor)
    for guest in guests:
        guest.refresh_from_db()
        assert guest.status == GuestStatus.IDLE
