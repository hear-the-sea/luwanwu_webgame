from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from gameplay.models import InventoryItem, ItemTemplate
from guests.models import Skill
from tests.guest_item_view_validation.support import bootstrap_guest_client


@pytest.mark.django_db
def test_learn_skill_view_rejects_invalid_item_id_redirect(game_data, django_user_model):
    _manor, guest, client = bootstrap_guest_client(game_data, django_user_model, username="view_learn_skill_invalid")

    response = client.post(
        reverse("guests:learn_skill", args=[guest.pk]),
        {"item_id": "invalid"},
    )

    assert response.status_code == 302
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("请选择技能书" in m for m in messages)


@pytest.mark.django_db
def test_learn_skill_view_rejects_non_mapping_effect_payload_redirect(game_data, django_user_model):
    manor, guest, client = bootstrap_guest_client(game_data, django_user_model, username="view_learn_skill_bad_payload")
    template = ItemTemplate.objects.create(
        key=f"view_learn_skill_bad_payload_{manor.id}",
        name="坏结构技能书",
        effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        effect_payload=False,
    )
    item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

    response = client.post(
        reverse("guests:learn_skill", args=[guest.pk]),
        {"item_id": str(item.pk)},
    )

    assert response.status_code == 302
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("技能书配置有误" in m for m in messages)


@pytest.mark.django_db
def test_learn_skill_view_rejects_non_string_skill_key_redirect(game_data, django_user_model):
    manor, guest, client = bootstrap_guest_client(
        game_data, django_user_model, username="view_learn_skill_bad_skill_key"
    )
    Skill.objects.create(key=f"view_learn_skill_unused_{manor.id}", name="测试技能")
    template = ItemTemplate.objects.create(
        key=f"view_learn_skill_bad_skill_key_{manor.id}",
        name="坏技能键技能书",
        effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        effect_payload={"skill_key": 123},
    )
    item = InventoryItem.objects.create(manor=manor, template=template, quantity=1)

    response = client.post(
        reverse("guests:learn_skill", args=[guest.pk]),
        {"item_id": str(item.pk)},
    )

    assert response.status_code == 302
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("技能书配置有误" in m for m in messages)


@pytest.mark.django_db
def test_forget_skill_view_rejects_invalid_guest_skill_id_redirect(game_data, django_user_model):
    _manor, guest, client = bootstrap_guest_client(game_data, django_user_model, username="view_forget_skill_invalid")

    response = client.post(
        reverse("guests:forget_skill", args=[guest.pk]),
        {"guest_skill_id": "invalid"},
    )

    assert response.status_code == 302
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("未指定技能" in m for m in messages)
