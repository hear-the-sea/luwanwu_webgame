"""
门客装备系统单元测试
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from guests.models import Guest, GuestTemplate, GuestRarity, GuestArchetype, GearTemplate, GearSlot, GearItem
from guests.services.equipment import equip_guest, unequip_guest_item

User = get_user_model()


class TestEquipmentHealthManagement(TestCase):
    """测试装备对生命值的影响"""

    def setUp(self):
        """测试前准备"""
        from gameplay.models import InventoryItem, ItemTemplate

        # 创建测试用户（庄园会自动创建）
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.manor = self.user.manor

        # 创建测试用门客模板
        self.template = GuestTemplate.objects.create(
            key="test_guest",
            name="测试门客",
            rarity=GuestRarity.BLUE,
            archetype=GuestArchetype.MILITARY,
            base_hp=1000,
        )

        # 创建测试门客（10级）
        # 新系统HP计算：base_hp + defense × 50 = 1000 + 180 × 50 = 10,000
        self.guest = Guest.objects.create(
            template=self.template,
            manor=self.manor,
            level=10,
            force=200,
            intellect=150,
            defense_stat=180,
            current_hp=10000,  # 当前满血（新系统：base_hp + defense×50）
        )

        # 创建物品模板（用于背包同步）
        self.InventoryItem = InventoryItem
        self.item_template = ItemTemplate.objects.create(
            key="test_ornament_hp",
            name="生命护符",
            effect_type="ornament",
            effect_payload={
                "hp": 200,  # 提供200点生命值
                "force": 10,
            },
            rarity=GuestRarity.BLUE,
        )

        # 创建装备模板
        self.gear_template = GearTemplate.objects.create(
            key="test_ornament_hp",
            name="生命护符",
            slot=GearSlot.ORNAMENT,
            rarity=GuestRarity.BLUE,
            extra_stats={
                "hp": 200,
                "force": 10,
            },
        )

    def test_unequip_reduces_max_hp_and_adjusts_current_hp(self):
        """测试：卸下装备后最大生命值降低，当前生命值自动调整"""
        # 1. 创建装备并装备到门客
        gear = GearItem.objects.create(manor=self.manor, template=self.gear_template)

        # 添加到背包（模拟装备来源）
        self.InventoryItem.objects.create(
            manor=self.manor,
            template=self.item_template,
            quantity=1
        )

        # 装备前的最大生命值（新系统：1000 + 180×50 = 10,000）
        max_hp_before = self.guest.max_hp
        self.assertEqual(max_hp_before, 10000)
        self.assertEqual(self.guest.current_hp, 10000)

        # 2. 装备道具（额外+200 HP）
        equip_guest(gear, self.guest)
        self.guest.refresh_from_db()

        # 装备后的最大生命值：10,000 + 200 = 10,200
        max_hp_equipped = self.guest.max_hp
        self.assertEqual(max_hp_equipped, 10200)

        # 假设门客受伤，当前生命值为10,100
        self.guest.current_hp = 10100
        self.guest.save(update_fields=["current_hp"])

        # 3. 卸下装备
        unequip_guest_item(gear, self.guest)
        self.guest.refresh_from_db()

        # 卸下后的最大生命值：10,000
        max_hp_after = self.guest.max_hp
        self.assertEqual(max_hp_after, 10000)

        # 当前生命值应该被调整为不超过最大生命值
        self.assertLessEqual(self.guest.current_hp, max_hp_after)
        self.assertEqual(self.guest.current_hp, 10000)

    def test_unequip_does_not_change_current_hp_if_below_max(self):
        """测试：卸下装备时，如果当前生命值低于新的最大生命值，则不改变"""
        # 1. 创建装备并装备
        gear = GearItem.objects.create(manor=self.manor, template=self.gear_template)
        self.InventoryItem.objects.create(
            manor=self.manor,
            template=self.item_template,
            quantity=1
        )

        equip_guest(gear, self.guest)
        self.guest.refresh_from_db()

        # 装备后最大生命值10,200，当前生命值设为8,000（低于卸下后的10,000）
        self.guest.current_hp = 8000
        self.guest.save(update_fields=["current_hp"])

        # 2. 卸下装备
        unequip_guest_item(gear, self.guest)
        self.guest.refresh_from_db()

        # 当前生命值不应改变
        self.assertEqual(self.guest.current_hp, 8000)

    def test_unequip_handles_zero_hp_case(self):
        """测试：卸下装备时处理0生命值的情况"""
        # 1. 创建装备并装备
        gear = GearItem.objects.create(manor=self.manor, template=self.gear_template)
        self.InventoryItem.objects.create(
            manor=self.manor,
            template=self.item_template,
            quantity=1
        )

        equip_guest(gear, self.guest)
        self.guest.refresh_from_db()

        # 门客阵亡，生命值为0
        self.guest.current_hp = 0
        self.guest.save(update_fields=["current_hp"])

        # 2. 卸下装备
        unequip_guest_item(gear, self.guest)
        self.guest.refresh_from_db()

        # 生命值应该保持为0
        self.assertEqual(self.guest.current_hp, 0)
