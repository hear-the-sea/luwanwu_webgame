from datetime import timedelta

import pytest
from django.utils import timezone

from gameplay.constants import MAX_CONCURRENT_BUILDING_UPGRADES
from gameplay.services.manor.core import ensure_manor, refresh_manor_state, start_upgrade


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
