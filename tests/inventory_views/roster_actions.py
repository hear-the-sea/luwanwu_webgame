import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from gameplay.models import InventoryItem, ItemTemplate
from guests.models import (
    GearItem,
    GearSlot,
    GearTemplate,
    Guest,
    GuestArchetype,
    GuestRarity,
    GuestStatus,
    GuestTemplate,
)


@pytest.mark.django_db
class TestInventoryRosterActions:
    def test_unequip_view_rejects_invalid_guest_id(self, manor_with_user):
        _manor, client = manor_with_user
        response = client.post(
            reverse("guests:unequip"),
            {"guest": "abc", "gear": []},
        )
        assert response.status_code == 302
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("参数错误" in m for m in messages)

    def test_unequip_view_rejects_invalid_gear_ids(self, manor_with_user):
        manor, client = manor_with_user
        guest_template = GuestTemplate.objects.create(
            key=f"view_unequip_invalid_gear_guest_tpl_{manor.id}",
            name="卸装门客模板",
            archetype=GuestArchetype.CIVIL,
            rarity=GuestRarity.GRAY,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.IDLE,
        )

        response = client.post(
            reverse("guests:unequip"),
            {"guest": str(guest.pk), "gear": ["abc"]},
        )
        assert response.status_code == 302
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("装备选择有误" in m for m in messages)

    def test_dismiss_guest_allows_injured_status_and_returns_equipped_gear(self, manor_with_user):
        manor, client = manor_with_user
        guest_template = GuestTemplate.objects.create(
            key=f"view_dismiss_injured_guest_tpl_{manor.id}",
            name="重伤辞退门客模板",
            archetype=GuestArchetype.CIVIL,
            rarity=GuestRarity.GRAY,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.INJURED,
        )
        gear_template = GearTemplate.objects.create(
            key=f"view_dismiss_injured_gear_tpl_{manor.id}",
            name="重伤辞退测试装备",
            slot=GearSlot.WEAPON,
            rarity=GuestRarity.GRAY,
        )
        item_template = ItemTemplate.objects.create(
            key=gear_template.key,
            name="重伤辞退测试装备道具",
            effect_type=ItemTemplate.EffectType.TOOL,
            effect_payload={},
            is_usable=True,
        )
        GearItem.objects.create(manor=manor, template=gear_template, guest=guest)

        response = client.post(reverse("guests:dismiss", kwargs={"pk": guest.pk}))

        assert response.status_code == 302
        assert response.url == reverse("guests:roster")
        assert not Guest.objects.filter(pk=guest.pk).exists()
        returned_item = InventoryItem.objects.get(
            manor=manor,
            template=item_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        assert returned_item.quantity == 1
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("已辞退" in m for m in messages)
