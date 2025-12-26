import pytest
from django.contrib.auth import get_user_model

from gameplay.models import ItemTemplate, Message, ResourceEvent, ResourceType
from gameplay.services import claim_message_attachments, ensure_manor

User = get_user_model()


@pytest.mark.django_db
def test_claim_message_attachments_records_actual_and_stores_claimed():
    user = User.objects.create_user(username="mail_user", password="pass123")
    manor = ensure_manor(user)

    manor.silver_capacity = 100
    manor.silver = 95
    manor.save(update_fields=["silver_capacity", "silver"])

    ItemTemplate.objects.create(
        key="mail_test_item",
        name="测试道具",
    )

    message = Message.objects.create(
        manor=manor,
        kind=Message.Kind.REWARD,
        title="测试邮件",
        attachments={
            "resources": {"silver": 20},
            "items": {"mail_test_item": 3},
        },
    )

    claimed = claim_message_attachments(message)

    assert claimed["silver"] == 5
    assert claimed["item_mail_test_item"] == 3

    message.refresh_from_db()
    assert message.is_claimed is True
    assert message.is_read is True
    assert message.attachments["resources"]["silver"] == 20
    assert message.attachments["items"]["mail_test_item"] == 3
    assert message.attachments["claimed"]["resources"]["silver"] == 5
    assert message.attachments["claimed"]["items"]["mail_test_item"] == 3

    manor.refresh_from_db()
    assert manor.silver == 100

    event = ResourceEvent.objects.filter(
        manor=manor,
        resource_type=ResourceType.SILVER,
        reason=ResourceEvent.Reason.ADMIN_ADJUST,
        note="邮件附件：测试邮件",
    ).first()
    assert event is not None
    assert event.delta == 5

    assert message.get_attachment_summary() == "银两×5、1种道具"

