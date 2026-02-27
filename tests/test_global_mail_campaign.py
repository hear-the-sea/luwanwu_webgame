from datetime import timedelta

import pytest
from django.utils import timezone

from gameplay.models import GlobalMailCampaign, GlobalMailDelivery, Message
from gameplay.services.global_mail import backfill_campaign_to_existing_manors
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
def test_backfill_campaign_to_existing_manors_is_idempotent(django_user_model):
    user_a = django_user_model.objects.create_user(username="global_mail_user_a", password="pass123")
    user_b = django_user_model.objects.create_user(username="global_mail_user_b", password="pass123")
    manor_a = ensure_manor(user_a)
    manor_b = ensure_manor(user_b)

    campaign = GlobalMailCampaign.objects.create(
        key="new_year_mail",
        kind=Message.Kind.REWARD,
        title="新年奖励",
        body="全服发放新年奖励",
        attachments={"resources": {"silver": 1000}, "items": {"peace_shield_small": 1}},
        is_active=True,
    )

    first_delivered = backfill_campaign_to_existing_manors(campaign)
    second_delivered = backfill_campaign_to_existing_manors(campaign)

    assert first_delivered == 2
    assert second_delivered == 0
    assert GlobalMailDelivery.objects.filter(campaign=campaign).count() == 2
    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor_a).exists()
    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor_b).exists()
    assert Message.objects.filter(title="新年奖励").count() == 2


@pytest.mark.django_db
def test_active_campaign_auto_delivered_for_new_manor(django_user_model):
    now = timezone.now()
    campaign = GlobalMailCampaign.objects.create(
        key="spring_mail",
        kind=Message.Kind.REWARD,
        title="春季福利",
        body="活动期间新用户也可领取",
        attachments={"resources": {"grain": 500}},
        is_active=True,
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(days=1),
    )

    user = django_user_model.objects.create_user(username="global_mail_new_user", password="pass123")
    manor = ensure_manor(user)

    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor).exists()
    assert Message.objects.filter(manor=manor, title="春季福利").exists()


@pytest.mark.django_db
def test_future_campaign_not_delivered_before_start(django_user_model):
    now = timezone.now()
    campaign = GlobalMailCampaign.objects.create(
        key="future_mail",
        kind=Message.Kind.SYSTEM,
        title="未来活动奖励",
        body="尚未开始",
        attachments={"resources": {"silver": 200}},
        is_active=True,
        start_at=now + timedelta(hours=6),
        end_at=now + timedelta(days=2),
    )

    user = django_user_model.objects.create_user(username="global_mail_future_user", password="pass123")
    manor = ensure_manor(user)

    assert GlobalMailDelivery.objects.filter(campaign=campaign, manor=manor).exists() is False
    assert Message.objects.filter(manor=manor, title="未来活动奖励").exists() is False
