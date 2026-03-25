from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from gameplay.models import RaidRun
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.combat.battle import process_raid_battle
from guests.models import Guest, GuestStatus, GuestTemplate


@pytest.mark.django_db
def test_process_raid_battle_does_not_finalize_retreat_before_return_at():
    """
    回归测试：撤退中的踢馆队伍不应在 battle_at（战斗任务触发）时被提前完成。

    否则会导致：临近到达时撤退，护院/门客在 battle_at 提前返程完成，绕过 return_at 计时。
    """
    User = get_user_model()
    attacker_user = User.objects.create_user(username="raid_attacker", password="pass123")
    defender_user = User.objects.create_user(username="raid_defender", password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    template = GuestTemplate.objects.first()
    assert template is not None
    guest = Guest.objects.create(
        manor=attacker,
        template=template,
        status=GuestStatus.DEPLOYED,
    )

    base_now = timezone.now()
    battle_at = base_now + timedelta(seconds=10)
    return_at = base_now + timedelta(seconds=30)

    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.RETREATED,
        travel_time=10,
        battle_at=battle_at,
        return_at=return_at,
    )
    run.guests.add(guest)

    # 在 battle_at 触发处理，不应提前完成撤退（return_at 仍在未来）
    process_raid_battle(run, now=battle_at)

    run.refresh_from_db()
    guest.refresh_from_db()
    assert run.status == RaidRun.Status.RETREATED
    assert run.completed_at is None
    assert guest.status == GuestStatus.DEPLOYED
