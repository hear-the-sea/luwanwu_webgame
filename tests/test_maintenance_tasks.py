from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from battle.models import BattleReport
from core.config import MESSAGE
from gameplay.models import ArenaExchangeRecord, Message, ResourceEvent, ResourceType
from gameplay.services.manor.core import ensure_manor
from gameplay.tasks.maintenance import (
    ARENA_EXCHANGE_RETENTION_DAYS,
    BATTLE_REPORT_RETENTION_DAYS,
    RESOURCE_EVENT_RETENTION_DAYS,
    cleanup_old_data_task,
)


def _create_battle_report(manor, *, opponent_name: str = "test-opponent") -> BattleReport:
    now = timezone.now()
    return BattleReport.objects.create(
        manor=manor,
        opponent_name=opponent_name,
        battle_type="skirmish",
        attacker_team=[],
        attacker_troops={},
        defender_team=[],
        defender_troops={},
        rounds=[],
        losses={},
        drops={},
        winner="attacker",
        starts_at=now,
        completed_at=now,
    )


@pytest.mark.django_db
def test_cleanup_old_data_task_cleans_old_rows_and_keeps_recent(django_user_model):
    user = django_user_model.objects.create_user(
        username="cleanup_old_data_user",
        password="pass123",
        email="cleanup_old_data_user@test.local",
    )
    manor = ensure_manor(user)

    now = timezone.now()

    old_resource_event = ResourceEvent.objects.create(
        manor=manor,
        resource_type=ResourceType.SILVER,
        delta=123,
        reason=ResourceEvent.Reason.ADMIN_ADJUST,
        note="old resource event",
    )
    new_resource_event = ResourceEvent.objects.create(
        manor=manor,
        resource_type=ResourceType.SILVER,
        delta=456,
        reason=ResourceEvent.Reason.ADMIN_ADJUST,
        note="new resource event",
    )
    ResourceEvent.objects.filter(pk=old_resource_event.pk).update(
        created_at=now - timedelta(days=RESOURCE_EVENT_RETENTION_DAYS + 1)
    )

    old_exchange = ArenaExchangeRecord.objects.create(
        manor=manor,
        reward_key="cleanup_reward_old",
        reward_name="旧兑换",
        cost_coins=100,
        quantity=1,
        payload={},
    )
    new_exchange = ArenaExchangeRecord.objects.create(
        manor=manor,
        reward_key="cleanup_reward_new",
        reward_name="新兑换",
        cost_coins=100,
        quantity=1,
        payload={},
    )
    ArenaExchangeRecord.objects.filter(pk=old_exchange.pk).update(
        created_at=now - timedelta(days=ARENA_EXCHANGE_RETENTION_DAYS + 1)
    )

    old_report = _create_battle_report(manor, opponent_name="old-report")
    new_report = _create_battle_report(manor, opponent_name="new-report")
    BattleReport.objects.filter(pk=old_report.pk).update(
        created_at=now - timedelta(days=BATTLE_REPORT_RETENTION_DAYS + 1)
    )

    old_message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="old message")
    new_message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="new message")
    Message.objects.filter(pk=old_message.pk).update(created_at=now - timedelta(days=MESSAGE.RETENTION_DAYS + 1))

    deleted_count = cleanup_old_data_task.run()
    assert deleted_count >= 4

    assert ResourceEvent.objects.filter(pk=old_resource_event.pk).exists() is False
    assert ArenaExchangeRecord.objects.filter(pk=old_exchange.pk).exists() is False
    assert BattleReport.objects.filter(pk=old_report.pk).exists() is False
    assert Message.objects.filter(pk=old_message.pk).exists() is False

    assert ResourceEvent.objects.filter(pk=new_resource_event.pk).exists() is True
    assert ArenaExchangeRecord.objects.filter(pk=new_exchange.pk).exists() is True
    assert BattleReport.objects.filter(pk=new_report.pk).exists() is True
    assert Message.objects.filter(pk=new_message.pk).exists() is True
