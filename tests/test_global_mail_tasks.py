from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from gameplay.models import GlobalMailCampaign, GlobalMailDelivery, Message
from gameplay.services.manor.core import ensure_manor
from gameplay.tasks.global_mail import backfill_global_mail_campaign_task, enqueue_global_mail_backfill


@pytest.mark.django_db
def test_backfill_global_mail_campaign_task_returns_not_found_for_missing_campaign():
    result = backfill_global_mail_campaign_task.run(999999)

    assert result["status"] == "not_found"
    assert result["campaign_id"] == 999999
    assert result["scanned"] == 0
    assert result["delivered"] == 0
    assert result["failed"] == 0


@pytest.mark.django_db
def test_backfill_global_mail_campaign_task_skips_inactive_campaign(django_user_model):
    user = django_user_model.objects.create_user(username="global_mail_task_inactive", password="pass123")
    ensure_manor(user)

    now = timezone.now()
    campaign = GlobalMailCampaign.objects.create(
        key="global_mail_task_future",
        kind=Message.Kind.REWARD,
        title="未来补发活动",
        body="尚未开始",
        attachments={"resources": {"silver": 100}},
        is_active=True,
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(days=1),
    )

    result = backfill_global_mail_campaign_task.run(campaign.id)

    assert result["status"] == "inactive"
    assert result["campaign_id"] == campaign.id
    assert result["scanned"] == 0
    assert result["delivered"] == 0
    assert result["failed"] == 0
    assert GlobalMailDelivery.objects.filter(campaign=campaign).count() == 0


@pytest.mark.django_db
def test_backfill_global_mail_campaign_task_is_idempotent(django_user_model):
    user_a = django_user_model.objects.create_user(username="global_mail_task_user_a", password="pass123")
    user_b = django_user_model.objects.create_user(username="global_mail_task_user_b", password="pass123")
    manor_a = ensure_manor(user_a)
    manor_b = ensure_manor(user_b)

    campaign = GlobalMailCampaign.objects.create(
        key="global_mail_task_active",
        kind=Message.Kind.REWARD,
        title="任务补发奖励",
        body="异步补发测试",
        attachments={"resources": {"grain": 88}, "items": {"peace_shield_small": 1}},
        is_active=True,
    )

    first_result = backfill_global_mail_campaign_task.run(campaign.id, batch_size=1)
    second_result = backfill_global_mail_campaign_task.run(campaign.id, batch_size=1)

    assert first_result["status"] == "ok"
    assert first_result["delivered"] == 2
    assert first_result["failed"] == 0
    assert first_result["scanned"] >= 2

    assert second_result["status"] == "ok"
    assert second_result["delivered"] == 0
    assert second_result["failed"] == 0
    assert second_result["scanned"] >= 2

    assert GlobalMailDelivery.objects.filter(campaign=campaign).count() == 2
    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor_a).exists()
    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor_b).exists()
    assert Message.objects.filter(title="任务补发奖励").count() == 2


@pytest.mark.django_db
def test_backfill_global_mail_campaign_task_records_failed_manor_ids(monkeypatch, django_user_model):
    user_a = django_user_model.objects.create_user(username="global_mail_task_fail_user_a", password="pass123")
    user_b = django_user_model.objects.create_user(username="global_mail_task_fail_user_b", password="pass123")
    manor_a = ensure_manor(user_a)
    manor_b = ensure_manor(user_b)

    campaign = GlobalMailCampaign.objects.create(
        key="global_mail_task_partial_failure",
        kind=Message.Kind.REWARD,
        title="任务补发失败记录",
        body="失败列表测试",
        attachments={"resources": {"wood": 10}},
        is_active=True,
    )

    original_deliver = backfill_global_mail_campaign_task.run.__globals__["deliver_campaign_to_manor"]

    def _deliver_with_failure(current_campaign, manor, now):
        if manor.id == manor_b.id:
            raise RuntimeError("boom")
        return original_deliver(current_campaign, manor, now=now)

    monkeypatch.setattr("gameplay.tasks.global_mail.deliver_campaign_to_manor", _deliver_with_failure)

    result = backfill_global_mail_campaign_task.run(campaign.id, batch_size=1)

    assert result["status"] == "partial_failure"
    assert result["delivered"] == 1
    assert result["failed"] == 1
    assert result["failed_manor_ids"] == [manor_b.id]
    assert str(manor_b.id) in result["summary"]
    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor_a).exists()
    assert not GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor_b).exists()


def test_enqueue_global_mail_backfill_submits_expected_args(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_apply_async(*_args, **kwargs):
        captured["args"] = kwargs.get("args")
        return None

    monkeypatch.setattr(backfill_global_mail_campaign_task, "apply_async", _fake_apply_async)

    result = enqueue_global_mail_backfill(7, batch_size=123)

    assert result is True
    assert captured["args"] == [7, 123]
