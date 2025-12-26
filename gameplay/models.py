from __future__ import annotations

import math
from datetime import timedelta
from typing import Dict

from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import BuildingKeys

# ============ 庄园容量常量 ============

# 门客容量：基础值 + 等级 × 每级增量（0级基础容量3，满级15级共18位）
GUEST_CAPACITY_BASE = 3
GUEST_CAPACITY_PER_LEVEL = 1

# 家丁容量：基础值 + 等级 × 每级增量（0级就有基础容量）
RETAINER_CAPACITY_BASE = 50
RETAINER_CAPACITY_PER_LEVEL = 100

# 出战上限：基础值 + 等级 × 每级增量，封顶值
SQUAD_SIZE_BASE = 3
SQUAD_SIZE_PER_LEVEL = 1
SQUAD_SIZE_MAX = 18

# 训练速度：10级满级提升30%，每级约3.33%
TRAINING_SPEED_BONUS_PER_LEVEL = 0.0333

# 制造速度：10级满级提升50%，每级约5.56%
PRODUCTION_SPEED_BONUS_PER_LEVEL = 0.0556

# 祠堂：5级满级，建造及募兵速度提升25%（时间减少20%）
CITANG_BUILDING_TIME_REDUCTION_PER_LEVEL = 0.05  # 每级减少5%建筑时间
CITANG_RECRUITMENT_SPEED_BONUS_PER_LEVEL = 0.0625  # 每级提升6.25%招募速度


class ResourceType(models.TextChoices):
    GRAIN = "grain", "粮食"
    SILVER = "silver", "银两"


class Manor(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="manor")
    name = models.CharField("庄园名称", max_length=20, unique=True, blank=True, null=True)
    grain = models.PositiveIntegerField("粮食", default=1200)
    silver = models.PositiveIntegerField("银两", default=500)
    storage_capacity = models.PositiveIntegerField("仓储上限", default=20000)
    silver_capacity = models.PositiveIntegerField("银库上限", default=20000)
    grain_capacity = models.PositiveIntegerField("粮仓上限", default=20000)
    retainer_count = models.PositiveIntegerField("家丁", default=0)
    prestige = models.PositiveIntegerField("声望", default=0)
    prestige_silver_spent = models.PositiveIntegerField("累计花费银两（声望计算用）", default=0)
    resource_updated_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    # ============ 庄园位置系统 ============
    region = models.CharField(
        "地区",
        max_length=32,
        default="overseas",
        db_index=True,
        help_text="庄园所在地区编码"
    )
    coordinate_x = models.PositiveIntegerField("X坐标", default=0)
    coordinate_y = models.PositiveIntegerField("Y坐标", default=0)
    last_active_at = models.DateTimeField("最后活跃时间", default=timezone.now)

    # ============ 保护机制 ============
    newbie_protection_until = models.DateTimeField(
        "新手保护截止时间",
        null=True,
        blank=True,
        help_text="注册后7天内免受攻击"
    )
    defeat_protection_until = models.DateTimeField(
        "战败保护截止时间",
        null=True,
        blank=True,
        help_text="被踢馆失败后30分钟保护"
    )
    peace_shield_until = models.DateTimeField(
        "免战牌保护截止时间",
        null=True,
        blank=True,
        help_text="使用免战牌后的保护时间"
    )
    last_relocation_at = models.DateTimeField(
        "上次迁移时间",
        null=True,
        blank=True,
        help_text="庄园迁移30天冷却"
    )

    class Meta:
        verbose_name = "庄园"
        verbose_name_plural = "庄园"
        constraints = [
            models.UniqueConstraint(
                fields=["region", "coordinate_x", "coordinate_y"],
                name="unique_manor_location",
                condition=models.Q(coordinate_x__gt=0, coordinate_y__gt=0),
            )
        ]
        indexes = [
            models.Index(fields=["region", "coordinate_x", "coordinate_y"]),
            models.Index(fields=["prestige"]),
        ]

    def __str__(self) -> str:
        return self.name or f"{self.user.username}的庄园"

    @property
    def display_name(self) -> str:
        """返回显示用的庄园名称"""
        return self.name or f"{self.user.username}的庄园"

    @property
    def region_display(self) -> str:
        """返回地区显示名称"""
        from .constants import REGION_DICT
        return REGION_DICT.get(self.region, self.region)

    @property
    def location_display(self) -> str:
        """返回完整位置显示，如：[浙江] (156, 423)"""
        return f"[{self.region_display}] ({self.coordinate_x}, {self.coordinate_y})"

    @property
    def is_under_newbie_protection(self) -> bool:
        """是否处于新手保护期"""
        if not self.newbie_protection_until:
            return False
        return self.newbie_protection_until > timezone.now()

    @property
    def is_under_defeat_protection(self) -> bool:
        """是否处于战败保护期"""
        if not self.defeat_protection_until:
            return False
        return self.defeat_protection_until > timezone.now()

    @property
    def is_under_peace_shield(self) -> bool:
        """是否处于免战牌保护期"""
        if not self.peace_shield_until:
            return False
        return self.peace_shield_until > timezone.now()

    @property
    def is_protected(self) -> bool:
        """是否处于任何保护状态"""
        return (
            self.is_under_newbie_protection
            or self.is_under_peace_shield
        )

    @property
    def can_relocate(self) -> bool:
        """是否可以迁移庄园"""
        from .constants import PVPConstants
        if self.is_under_newbie_protection:
            return False
        if self.last_relocation_at:
            from datetime import timedelta
            cooldown_end = self.last_relocation_at + timedelta(days=PVPConstants.RELOCATION_COOLDOWN_DAYS)
            if cooldown_end > timezone.now():
                return False
        return True

    def resource_dict(self) -> Dict[str, int]:
        return {field: getattr(self, field) for field in ResourceType.values}

    # ============ 建筑等级缓存（优化 N+1 查询）============
    # 这些 property 会频繁访问，使用实例级缓存避免重复查询
    # 缓存在请求结束后自动失效（实例被回收）

    def _get_building_levels_cache(self) -> Dict[str, int]:
        """
        获取建筑等级缓存，一次查询加载所有关键建筑等级。

        优化前：每个 property 独立查询（4次查询）
        优化后：首次访问时批量查询，后续使用缓存（1次查询）
        """
        if not hasattr(self, "_building_levels"):
            # 批量查询所有关键建筑
            key_buildings = [
                BuildingKeys.JUXIAN_ZHUANG,
                BuildingKeys.JIADING_FANG,
                BuildingKeys.YOUXIA_BAOTA,
                BuildingKeys.LIANGGONG_CHANG,
                BuildingKeys.TREASURY,
                BuildingKeys.BATHHOUSE,
                BuildingKeys.SILVER_VAULT,
                BuildingKeys.GRANARY,
                BuildingKeys.RANCH,
                BuildingKeys.SMITHY,
                BuildingKeys.STABLE,
                BuildingKeys.TAVERN,
                BuildingKeys.CITANG,
            ]
            buildings = self.buildings.select_related("building_type").filter(
                building_type__key__in=key_buildings
            )
            self._building_levels = {b.building_type.key: b.level for b in buildings}
        return self._building_levels

    def invalidate_building_cache(self) -> None:
        """
        使建筑等级缓存失效。

        在建筑升级完成后调用此方法，确保下次访问时重新加载。
        """
        if hasattr(self, "_building_levels"):
            del self._building_levels

    def get_building_level(self, building_key: str) -> int:
        """获取指定建筑的等级，使用缓存"""
        cache = self._get_building_levels_cache()
        return cache.get(building_key, 1)

    @property
    def guest_capacity(self) -> int:
        """门客容量：基础值 + 聚贤庄等级 × 每级增量（0级3位，满级15级18位）"""
        level = self.get_building_level(BuildingKeys.JUXIAN_ZHUANG)
        return GUEST_CAPACITY_BASE + level * GUEST_CAPACITY_PER_LEVEL

    @property
    def retainer_capacity(self) -> int:
        """家丁容量：基础值 + 家丁房等级 × 每级增量（0级就有50个基础位置）"""
        level = self.get_building_level(BuildingKeys.JIADING_FANG)
        return RETAINER_CAPACITY_BASE + level * RETAINER_CAPACITY_PER_LEVEL

    @property
    def max_squad_size(self) -> int:
        """
        出战上限：基础值 + 游侠宝塔等级 × 每级增量，封顶 SQUAD_SIZE_MAX。
        0级3人，每级+1人，15级满级18人。
        """
        level = self.get_building_level(BuildingKeys.YOUXIA_BAOTA)
        return min(SQUAD_SIZE_MAX, SQUAD_SIZE_BASE + level * SQUAD_SIZE_PER_LEVEL)

    @property
    def guard_training_speed_multiplier(self) -> float:
        """
        练功场训练速度加成，每级增加 TRAINING_SPEED_BONUS_PER_LEVEL。
        """
        level = self.get_building_level(BuildingKeys.LIANGGONG_CHANG)
        return 1.0 + max(0, level - 1) * TRAINING_SPEED_BONUS_PER_LEVEL

    @property
    def hp_recovery_multiplier(self) -> float:
        """
        澡堂生命恢复加成，满级(20级)提供200%加成。
        每级增加10%，即 level * 0.10。
        1级=10%, 20级=200%
        """
        level = self.get_building_level(BuildingKeys.BATHHOUSE)
        return 1.0 + level * 0.10

    @property
    def calculated_silver_capacity(self) -> int:
        """
        银库容量：根据银库建筑等级计算。
        1级: 20,000  30级: 40,000,000
        公式: base * (growth ^ (level - 1))
        growth ≈ 1.299657
        """
        level = self.get_building_level(BuildingKeys.SILVER_VAULT)
        base = 20000
        growth = 1.299657
        return int(base * (growth ** (level - 1)))

    @property
    def calculated_grain_capacity(self) -> int:
        """
        粮仓容量：根据粮仓建筑等级计算。
        1级: 20,000  20级: 10,500,000
        公式: base * (growth ^ (level - 1))
        growth ≈ 1.3905
        """
        level = self.get_building_level(BuildingKeys.GRANARY)
        base = 20000
        growth = 1.3905
        return int(base * (growth ** (level - 1)))

    @property
    def livestock_production_multiplier(self) -> float:
        """
        畜牧场家畜制造速度加成。
        10级满级提升50%，每级约5.56%。
        """
        level = self.get_building_level(BuildingKeys.RANCH)
        return 1.0 + max(0, level - 1) * PRODUCTION_SPEED_BONUS_PER_LEVEL

    @property
    def smithy_production_multiplier(self) -> float:
        """
        冶炼坊物资制造速度加成。
        10级满级提升50%，每级约5.56%。
        """
        level = self.get_building_level(BuildingKeys.SMITHY)
        return 1.0 + max(0, level - 1) * PRODUCTION_SPEED_BONUS_PER_LEVEL

    @property
    def stable_production_multiplier(self) -> float:
        """
        马房马匹制造速度加成。
        10级满级提升50%，每级约5.56%。
        """
        level = self.get_building_level(BuildingKeys.STABLE)
        return 1.0 + max(0, level - 1) * PRODUCTION_SPEED_BONUS_PER_LEVEL

    @property
    def tavern_recruitment_bonus(self) -> int:
        """
        酒馆招募候选人数加成。
        10级满级增加10位候选人，每级增加1位。
        """
        level = self.get_building_level(BuildingKeys.TAVERN)
        return level

    @property
    def citang_building_time_reduction(self) -> float:
        """
        祠堂建筑升级时间减少比例。
        5级满级减少20%，每级减少5%。
        返回值为减少比例（如 0.2 表示减少20%，实际时间为原来的80%）。
        """
        level = self.get_building_level(BuildingKeys.CITANG)
        return max(0, level - 1) * CITANG_BUILDING_TIME_REDUCTION_PER_LEVEL

    @property
    def citang_recruitment_speed_multiplier(self) -> float:
        """
        祠堂护院招募速度加成倍率。
        5级满级提升25%，每级提升6.25%。
        返回值为速度倍率（如 1.25 表示速度为原来的125%，时间缩短为原来的80%）。
        """
        level = self.get_building_level(BuildingKeys.CITANG)
        return 1.0 + max(0, level - 1) * CITANG_RECRUITMENT_SPEED_BONUS_PER_LEVEL


class BuildingCategory(models.TextChoices):
    RESOURCE = "resource", "资源生产"
    STORAGE = "storage", "仓储设施"
    PRODUCTION = "production", "生产加工"
    PERSONNEL = "personnel", "人员管理"
    SPECIAL = "special", "特殊建筑"


class BuildingType(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField("建筑名称", max_length=64)
    description = models.TextField(blank=True)
    category = models.CharField(
        "建筑分类",
        max_length=16,
        choices=BuildingCategory.choices,
        default=BuildingCategory.RESOURCE,
    )
    resource_type = models.CharField(max_length=16, choices=ResourceType.choices)
    base_rate_per_hour = models.PositiveIntegerField("一级产量(每小时)", default=50)
    rate_growth = models.FloatField("每级增长系数", default=0.15)
    base_upgrade_time = models.PositiveIntegerField("一级建造时间(秒)", default=60)
    time_growth = models.FloatField("时间成长系数", default=1.25)
    base_cost = models.JSONField(default=dict)
    cost_growth = models.FloatField("成本成长系数", default=1.35)
    icon = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = "建筑类型"
        verbose_name_plural = "建筑类型"

    def __str__(self) -> str:
        return self.name


class Building(models.Model):
    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="buildings")
    building_type = models.ForeignKey(BuildingType, on_delete=models.CASCADE, related_name="instances")
    level = models.PositiveIntegerField(default=1)
    is_upgrading = models.BooleanField(default=False)
    upgrade_complete_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "建筑"
        verbose_name_plural = "建筑"
        unique_together = ("manor", "building_type")
        indexes = [
            models.Index(fields=["manor", "is_upgrading", "upgrade_complete_at"], name="building_upgrade_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username}-{self.building_type.name}-Lv{self.level}"

    def hourly_rate(self) -> float:
        growth = 1 + self.building_type.rate_growth * (self.level - 1)
        return self.building_type.base_rate_per_hour * growth

    def next_level_cost(self) -> Dict[str, int]:
        target_level = self.level + 1
        multiplier = self.building_type.cost_growth ** (target_level - 1)
        return {
            resource: math.ceil(amount * multiplier)
            for resource, amount in (self.building_type.base_cost or {}).items()
        }

    def next_level_duration(self) -> int:
        target_level = self.level + 1
        multiplier = self.building_type.time_growth ** (target_level - 1)
        return math.ceil(self.building_type.base_upgrade_time * multiplier)


class ResourceEvent(models.Model):
    class Reason(models.TextChoices):
        PRODUCE = "produce", "自动产出"
        UPGRADE_COST = "upgrade_cost", "建筑升级"
        TASK_REWARD = "task_reward", "任务奖励"
        BATTLE_REWARD = "battle_reward", "战斗掉落"
        ADMIN_ADJUST = "admin_adjust", "运营调整"
        RECRUIT_COST = "recruit_cost", "门客招募"
        TRAINING_COST = "training_cost", "门客培养"
        ITEM_USE = "item_use", "道具使用"
        SHOP_PURCHASE = "shop_purchase", "商铺购买"
        SHOP_SELL = "shop_sell", "商铺出售"
        WORK_REWARD = "work_reward", "打工报酬"
        GUILD_DONATION = "guild_donation", "帮会捐献"
        MARKET_LISTING_FEE = "market_listing_fee", "交易行挂单手续费"
        MARKET_PURCHASE = "market_purchase", "交易行购买"
        MARKET_SOLD = "market_sold", "交易行出售"
        ITEM_SOLD = "item_sold", "物品出售"
        TECH_UPGRADE = "tech_upgrade", "科技升级"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="resource_events")
    resource_type = models.CharField(max_length=16, choices=ResourceType.choices)
    delta = models.IntegerField()
    reason = models.CharField(max_length=32, choices=Reason.choices)
    note = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "资源流水"
        verbose_name_plural = "资源流水"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["manor", "-created_at"]),
            models.Index(fields=["manor", "reason", "-created_at"]),
        ]


class ItemTemplate(models.Model):
    class EffectType(models.TextChoices):
        RESOURCE_PACK = "resource_pack", "资源补给"
        RESOURCE = "resource", "资源"
        SKILL_BOOK = "skill_book", "技能书"
        EXPERIENCE_ITEM = "experience_items", "经验道具"
        MEDICINE = "medicine", "药品"
        TOOL = "tool", "道具"

    key = models.SlugField(unique=True)
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    effect_type = models.CharField(max_length=32, choices=EffectType.choices, default=EffectType.RESOURCE_PACK)
    effect_payload = models.JSONField(default=dict, blank=True)
    icon = models.CharField(max_length=32, blank=True)
    image = models.ImageField(upload_to='items/', blank=True, null=True, verbose_name="物品图片")
    rarity = models.CharField(max_length=16, default="gray")
    tradeable = models.BooleanField(default=False)
    price = models.PositiveIntegerField(default=0)
    storage_space = models.PositiveIntegerField(default=1, verbose_name="占用空间")
    is_usable = models.BooleanField(default=False, verbose_name="可在仓库使用")

    class Meta:
        verbose_name = "物品模板"
        verbose_name_plural = "物品模板"

    def __str__(self) -> str:
        return self.name


class InventoryItem(models.Model):
    class StorageLocation(models.TextChoices):
        WAREHOUSE = "warehouse", "仓库"
        TREASURY = "treasury", "藏宝阁"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="inventory_items")
    template = models.ForeignKey(ItemTemplate, on_delete=models.CASCADE, related_name="inventory_entries")
    quantity = models.PositiveIntegerField(default=0)
    storage_location = models.CharField(max_length=16, choices=StorageLocation.choices, default=StorageLocation.WAREHOUSE, verbose_name="存储位置")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "仓库物品"
        verbose_name_plural = "仓库物品"
        unique_together = ("manor", "template", "storage_location")
        indexes = [
            models.Index(fields=["manor", "storage_location", "quantity"], name="inventory_manor_loc_qty_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor} - {self.template.name} x{self.quantity}"

    @property
    def effect_summary(self) -> str:
        payload = self.template.effect_payload or {}
        effect_type = self.template.effect_type
        if effect_type == ItemTemplate.EffectType.RESOURCE_PACK and payload:
            labels = dict(ResourceType.choices)
            parts = []
            for key, amount in payload.items():
                label = labels.get(key, key)
                parts.append(f"{label} +{amount}")
            return "、".join(parts)
        if effect_type == ItemTemplate.EffectType.SKILL_BOOK:
            skill_name = payload.get("skill_name") or payload.get("skill_key", "技能")
            return f"学习 {skill_name}"
        if effect_type and effect_type.startswith("equip_"):
            stat_labels = {
                "hp": "生命",
                "force": "武力",
                "intellect": "智力",
                "defense": "防御",
                "agility": "敏捷",
                "luck": "运势",
                "troop_capacity": "可携带护院人数",
                "attack": "攻击",
                "defense_bonus": "防御",
            }
            parts = []
            payload = payload or {}
            set_desc = payload.get("set_description")
            set_bonus = payload.get("set_bonus") or {}
            for key, value in payload.items():
                if value is None:
                    continue
                if key in {"set_key", "set_bonus", "set_description"}:
                    continue
                label = stat_labels.get(key, key)
                parts.append(f"{label}+{value}")
            set_text = ""
            if set_desc or set_bonus:
                pieces = set_bonus.get("pieces") if isinstance(set_bonus, dict) else None
                bonus_map = set_bonus.get("bonus") if isinstance(set_bonus, dict) else None
                bonus_parts = []
                if isinstance(bonus_map, dict):
                    for key, value in bonus_map.items():
                        if value is None:
                            continue
                        label = stat_labels.get(key, key)
                        bonus_parts.append(f"{label}+{value}")
                desc_text = set_desc or "套装"
                piece_text = f"（{pieces}件）" if pieces else ""
                if bonus_parts:
                    set_text = f"{desc_text}{piece_text}：" + "、".join(bonus_parts)
                else:
                    set_text = f"{desc_text}{piece_text}"
            if set_text:
                return ("、".join(parts) + "；" if parts else "") + set_text
            return "、".join(parts) or "提升属性"
        if effect_type == ItemTemplate.EffectType.MEDICINE:
            hp = payload.get("hp")
            if hp:
                return f"恢复生命 +{hp}"
            return "恢复生命"
        if effect_type == ItemTemplate.EffectType.TOOL:
            key = self.template.key or ""
            if key == "fangdajing":
                return "显现候选稀有度"
            if key.startswith("peace_shield_"):
                duration = payload.get("duration")
                if duration:
                    hours = duration // 3600
                    if hours % 24 == 0:
                        return f"免战保护 {hours // 24} 天"
                    return f"免战保护 {hours} 小时"
                return "免战保护"
            if key == "manor_rename_card":
                return "更换庄园名称"
            return "道具"
        return "无特殊效果"

    @property
    def can_use_in_warehouse(self) -> bool:
        return self.template.is_usable

    @property
    def warehouse_use_hint(self) -> str:
        if self.can_use_in_warehouse:
            return ""
        return "此物品不可在仓库使用"

    @property
    def category_display(self) -> str:
        """获取物品种类显示名称"""
        effect_type = self.template.effect_type or ""
        category_map = {
            "resource_pack": "资源包",
            "resource": "资源",
            "skill_book": "技能书",
            "experience_items": "经验",
            "medicine": "药品",
            "tool": "道具",
            "equip_helmet": "头盔",
            "equip_armor": "衣服",
            "equip_shoes": "鞋子",
            "equip_weapon": "武器",
            "equip_mount": "坐骑",
            "equip_ornament": "饰品",
            "equip_device": "器械",
        }
        if effect_type.startswith("equip_"):
            return category_map.get(effect_type, "装备")
        return category_map.get(effect_type, "其他")


class Message(models.Model):
    class Kind(models.TextChoices):
        BATTLE = "battle", "战报"
        SYSTEM = "system", "系统"
        REWARD = "reward", "奖励"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="messages")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField(max_length=128)
    body = models.TextField(blank=True)
    battle_report = models.ForeignKey(
        "battle.BattleReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    attachments = models.JSONField("附件数据", default=dict, blank=True)
    is_claimed = models.BooleanField("已领取", default=False)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "消息"
        verbose_name_plural = "消息"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["manor", "is_read", "-created_at"]),
            models.Index(fields=["manor", "is_claimed"]),
            models.Index(fields=["manor", "kind", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.get_kind_display()}] {self.title}"

    @property
    def has_attachments(self) -> bool:
        """检查是否有附件"""
        if not self.attachments:
            return False
        items = self.attachments.get("items", {})
        resources = self.attachments.get("resources", {})
        return bool(items or resources)

    def get_attachment_summary(self) -> str:
        """获取附件摘要，用于列表显示"""
        if not self.has_attachments:
            return ""

        parts = []
        attachments = self.attachments or {}
        resources = attachments.get("resources", {})
        items = attachments.get("items", {})

        if self.is_claimed:
            claimed = attachments.get("claimed")
            if isinstance(claimed, dict):
                resources = claimed.get("resources", {}) or {}
                items = claimed.get("items", {}) or {}

        resource_labels = dict(ResourceType.choices)
        for key, amount in resources.items():
            label = resource_labels.get(key, key)
            parts.append(f"{label}×{amount}")

        # 物品数量统计
        if items:
            parts.append(f"{len(items)}种道具")

        return "、".join(parts) if parts else "附件"


class MissionTemplate(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    battle_type = models.CharField(max_length=32, default="task")
    is_defense = models.BooleanField(default=False, help_text="敌方主动来袭，玩家为防守方")
    enemy_guests = models.JSONField(default=list, blank=True)
    enemy_troops = models.JSONField(default=dict, blank=True)
    enemy_technology = models.JSONField(default=dict, blank=True, help_text="敌方护院科技配置")
    drop_table = models.JSONField(default=dict, blank=True)
    probability_drop_table = models.JSONField(default=dict, blank=True, help_text="概率掉落表")
    base_travel_time = models.PositiveIntegerField(default=1200, help_text="往返基础耗时（秒）")
    daily_limit = models.PositiveIntegerField(default=3)

    class Meta:
        verbose_name = "任务模板"
        verbose_name_plural = "任务模板"

    def __str__(self) -> str:
        return self.name


class MissionRun(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "出征中"
        COMPLETED = "completed", "已返程"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="mission_runs")
    mission = models.ForeignKey(MissionTemplate, on_delete=models.CASCADE, related_name="runs")
    guests = models.ManyToManyField("guests.Guest", related_name="mission_runs", blank=True)
    troop_loadout = models.JSONField(default=dict, blank=True)
    battle_report = models.ForeignKey("battle.BattleReport", null=True, blank=True, on_delete=models.SET_NULL)
    travel_time = models.PositiveIntegerField(default=0, help_text="单程耗时（秒）")
    started_at = models.DateTimeField(auto_now_add=True)
    return_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    is_retreating = models.BooleanField(default=False)

    class Meta:
        verbose_name = "任务出征"
        verbose_name_plural = "任务出征"
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["status", "return_at"]),
            models.Index(fields=["manor", "status"]),
            models.Index(fields=["manor", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.manor} - {self.mission.name}"

    @property
    def battle_at(self):
        """战斗时间点（去程结束时间）"""
        if not self.started_at or not self.travel_time:
            return None
        return self.started_at + timedelta(seconds=self.travel_time)

    @property
    def is_returning(self) -> bool:
        """是否处于返程阶段"""
        if self.is_retreating:
            return True
        battle_at = self.battle_at
        if not battle_at:
            return False
        return timezone.now() >= battle_at

    @property
    def next_state_at(self):
        """下一个状态的时间点（用于事件栏显示）"""
        if self.is_returning:
            return self.return_at
        return self.battle_at

    @property
    def time_remaining(self) -> int:
        next_at = self.next_state_at
        if not next_at:
            return 0
        delta = next_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class PlayerTechnology(models.Model):
    """玩家技术等级"""
    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="technologies")
    tech_key = models.CharField("技术标识", max_length=64)
    level = models.PositiveIntegerField("等级", default=0)
    is_upgrading = models.BooleanField("升级中", default=False)
    upgrade_complete_at = models.DateTimeField("升级完成时间", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "玩家技术"
        verbose_name_plural = "玩家技术"
        unique_together = ("manor", "tech_key")
        indexes = [
            models.Index(fields=["manor", "is_upgrading", "upgrade_complete_at"], name="tech_upgrade_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.tech_key} Lv{self.level}"

    def upgrade_duration(self) -> int:
        """
        计算升级到下一级所需的时间（秒）。

        公式: base_time * (1.4 ^ level)
        普通技能：
        - 0->1级: 60秒 (1分钟)
        - 1->2级: 84秒 (1.4分钟)
        - 2->3级: 118秒 (约2分钟)
        - 5->6级: 323秒 (约5.4分钟)
        - 9->10级: 1208秒 (约20分钟)

        特殊技能（base_time=300）：
        - 0->1级: 300秒 (5分钟)
        - 4->5级: 1152秒 (约19分钟)
        """
        from core.utils.time_scale import scale_duration
        from gameplay.services.technology import get_technology_template

        template = get_technology_template(self.tech_key)
        base_time = template.get("base_time", 60) if template else 60
        raw = base_time * (1.4 ** self.level)
        return scale_duration(raw, minimum=1)

    @property
    def time_remaining(self) -> int:
        """剩余升级时间（秒）"""
        if not self.upgrade_complete_at:
            return 0
        delta = self.upgrade_complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class WorkTemplate(models.Model):
    """工作地点模板"""

    class Tier(models.TextChoices):
        JUNIOR = "junior", "初级工作区"
        INTERMEDIATE = "intermediate", "中级工作区"
        SENIOR = "senior", "高级工作区"

    key = models.SlugField(unique=True, verbose_name="工作标识")
    name = models.CharField(max_length=64, verbose_name="工作名称")
    description = models.TextField(blank=True, verbose_name="工作简介")
    tier = models.CharField(
        max_length=16,
        choices=Tier.choices,
        default=Tier.JUNIOR,
        verbose_name="工作区等级"
    )

    # 工作要求
    required_level = models.PositiveIntegerField(default=1, verbose_name="等级要求")
    required_force = models.PositiveIntegerField(default=0, verbose_name="武力要求")
    required_intellect = models.PositiveIntegerField(default=0, verbose_name="智力要求")

    # 工作报酬
    reward_silver = models.PositiveIntegerField(default=0, verbose_name="银两报酬")

    # 工作时长（秒）
    work_duration = models.PositiveIntegerField(default=7200, verbose_name="工作时长")

    # 显示顺序
    display_order = models.PositiveIntegerField(default=0, verbose_name="显示顺序")

    # 图标
    icon = models.CharField(max_length=32, blank=True, verbose_name="图标")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "工作模板"
        verbose_name_plural = "工作模板"
        ordering = ["tier", "display_order", "required_level"]

    def __str__(self) -> str:
        return f"{self.name}（{self.get_tier_display()}）"


class WorkAssignment(models.Model):
    """门客打工记录"""

    class Status(models.TextChoices):
        WORKING = "working", "打工中"
        COMPLETED = "completed", "已完成"
        RECALLED = "recalled", "已召回"

    manor = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="work_assignments",
        verbose_name="庄园"
    )
    guest = models.ForeignKey(
        "guests.Guest",
        on_delete=models.CASCADE,
        related_name="work_assignments",
        verbose_name="门客"
    )
    work_template = models.ForeignKey(
        WorkTemplate,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="工作地点"
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.WORKING,
        verbose_name="状态"
    )

    # 时间记录
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="开始时间")
    complete_at = models.DateTimeField(verbose_name="完成时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="实际完成时间")

    # 报酬记录
    reward_claimed = models.BooleanField(default=False, verbose_name="已领取报酬")

    class Meta:
        verbose_name = "打工记录"
        verbose_name_plural = "打工记录"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "-started_at"]),
            models.Index(fields=["guest", "-started_at"]),
            models.Index(fields=["manor", "status", "complete_at"], name="work_manor_sts_comp_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.guest.name} - {self.work_template.name}"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.WORKING:
            return 0
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class PlayerTroop(models.Model):
    """玩家护院存储"""
    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="troops")
    troop_template = models.ForeignKey(
        "battle.TroopTemplate",
        on_delete=models.CASCADE,
        related_name="player_troops",
        verbose_name="兵种模板"
    )
    count = models.PositiveIntegerField("数量", default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "玩家护院"
        verbose_name_plural = "玩家护院"
        unique_together = ("manor", "troop_template")

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.troop_template.name} x{self.count}"


class HorseProduction(models.Model):
    """马匹生产队列"""

    class Status(models.TextChoices):
        PRODUCING = "producing", "生产中"
        COMPLETED = "completed", "已完成"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="horse_productions")
    horse_key = models.CharField("马匹key", max_length=64)
    horse_name = models.CharField("马匹名称", max_length=64)
    quantity = models.PositiveIntegerField("生产数量", default=1)
    grain_cost = models.PositiveIntegerField("粮食消耗")
    base_duration = models.PositiveIntegerField("基础时长(秒)")
    actual_duration = models.PositiveIntegerField("实际时长(秒)")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PRODUCING)
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    complete_at = models.DateTimeField("完成时间")
    finished_at = models.DateTimeField("实际完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "马匹生产"
        verbose_name_plural = "马匹生产"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "complete_at"], name="horse_status_complete_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.horse_name} ({self.status})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.PRODUCING:
            return 0
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class LivestockProduction(models.Model):
    """家畜养殖队列"""

    class Status(models.TextChoices):
        PRODUCING = "producing", "养殖中"
        COMPLETED = "completed", "已完成"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="livestock_productions")
    livestock_key = models.CharField("家畜key", max_length=64)
    livestock_name = models.CharField("家畜名称", max_length=64)
    quantity = models.PositiveIntegerField("养殖数量", default=1)
    grain_cost = models.PositiveIntegerField("粮食消耗")
    base_duration = models.PositiveIntegerField("基础时长(秒)")
    actual_duration = models.PositiveIntegerField("实际时长(秒)")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PRODUCING)
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    complete_at = models.DateTimeField("完成时间")
    finished_at = models.DateTimeField("实际完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "家畜养殖"
        verbose_name_plural = "家畜养殖"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "complete_at"], name="livestock_status_complete_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.livestock_name} ({self.status})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.PRODUCING:
            return 0
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class SmeltingProduction(models.Model):
    """金属冶炼队列"""

    class Status(models.TextChoices):
        PRODUCING = "producing", "冶炼中"
        COMPLETED = "completed", "已完成"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="smelting_productions")
    metal_key = models.CharField("金属key", max_length=64)
    metal_name = models.CharField("金属名称", max_length=64)
    quantity = models.PositiveIntegerField("冶炼数量", default=1)
    cost_type = models.CharField("消耗类型", max_length=32, default="silver")
    cost_amount = models.PositiveIntegerField("消耗数量", default=0)
    base_duration = models.PositiveIntegerField("基础时长(秒)")
    actual_duration = models.PositiveIntegerField("实际时长(秒)")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PRODUCING)
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    complete_at = models.DateTimeField("完成时间")
    finished_at = models.DateTimeField("实际完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "金属冶炼"
        verbose_name_plural = "金属冶炼"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "complete_at"], name="smelting_status_complete_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.metal_name} ({self.status})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.PRODUCING:
            return 0
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class EquipmentProduction(models.Model):
    """装备锻造队列"""

    class Status(models.TextChoices):
        FORGING = "forging", "锻造中"
        COMPLETED = "completed", "已完成"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="equipment_productions")
    equipment_key = models.CharField("装备key", max_length=64)
    equipment_name = models.CharField("装备名称", max_length=64)
    quantity = models.PositiveIntegerField("锻造数量", default=1)
    material_costs = models.JSONField("材料消耗", default=dict)
    base_duration = models.PositiveIntegerField("基础时长(秒)")
    actual_duration = models.PositiveIntegerField("实际时长(秒)")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.FORGING)
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    complete_at = models.DateTimeField("完成时间")
    finished_at = models.DateTimeField("实际完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "装备锻造"
        verbose_name_plural = "装备锻造"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "complete_at"], name="equipment_status_complete_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.equipment_name} ({self.status})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.FORGING:
            return 0
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class TroopRecruitment(models.Model):
    """护院募兵队列"""

    class Status(models.TextChoices):
        RECRUITING = "recruiting", "募兵中"
        COMPLETED = "completed", "已完成"

    manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="troop_recruitments")
    troop_key = models.CharField("兵种key", max_length=64)
    troop_name = models.CharField("兵种名称", max_length=64)
    quantity = models.PositiveIntegerField("募兵数量", default=1)
    equipment_costs = models.JSONField("装备消耗", default=dict)
    retainer_cost = models.PositiveIntegerField("家丁消耗", default=1)
    base_duration = models.PositiveIntegerField("基础时长(秒)")
    actual_duration = models.PositiveIntegerField("实际时长(秒)")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECRUITING)
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    complete_at = models.DateTimeField("完成时间")
    finished_at = models.DateTimeField("实际完成时间", null=True, blank=True)

    class Meta:
        verbose_name = "护院募兵"
        verbose_name_plural = "护院募兵"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "complete_at"], name="troop_status_complete_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.manor.user.username} - {self.troop_name} x{self.quantity} ({self.status})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.RECRUITING:
            return 0
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))


# ============ PVP 踢馆系统模型 ============


class ScoutRecord(models.Model):
    """侦察记录"""

    class Status(models.TextChoices):
        SCOUTING = "scouting", "侦察中"
        RETURNING = "returning", "返程中"
        SUCCESS = "success", "侦察成功"
        FAILED = "failed", "侦察失败"

    attacker = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="scout_records_sent",
        verbose_name="发起方"
    )
    defender = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="scout_records_received",
        verbose_name="目标方"
    )
    status = models.CharField(
        "状态",
        max_length=16,
        choices=Status.choices,
        default=Status.SCOUTING
    )
    scout_cost = models.PositiveIntegerField("消耗探子数", default=1)
    success_rate = models.FloatField("成功率", default=0.5)
    travel_time = models.PositiveIntegerField("单程时间(秒)", default=60)
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    complete_at = models.DateTimeField("到达时间")
    return_at = models.DateTimeField("返程完成时间", null=True, blank=True)
    completed_at = models.DateTimeField("实际完成时间", null=True, blank=True)
    is_success = models.BooleanField("是否成功", null=True, blank=True)

    # 侦察结果（成功时填充）
    intel_data = models.JSONField(
        "情报数据",
        default=dict,
        blank=True,
        help_text="包含目标庄园的门客、兵力、资源等信息"
    )

    class Meta:
        verbose_name = "侦察记录"
        verbose_name_plural = "侦察记录"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["attacker", "defender", "-started_at"]),
            models.Index(fields=["status", "complete_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.attacker.display_name} -> {self.defender.display_name} ({self.get_status_display()})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        now = timezone.now()
        if self.status == self.Status.SCOUTING:
            delta = self.complete_at - now
            return max(0, int(delta.total_seconds()))
        elif self.status == self.Status.RETURNING and self.return_at:
            delta = self.return_at - now
            return max(0, int(delta.total_seconds()))
        return 0

    @property
    def next_state_at(self):
        """下一个状态的时间点（用于事件栏显示）"""
        if self.status == self.Status.SCOUTING:
            return self.complete_at
        elif self.status == self.Status.RETURNING:
            return self.return_at
        return None


class ScoutCooldown(models.Model):
    """侦察冷却记录（同一目标30分钟冷却）"""

    attacker = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="scout_cooldowns_sent"
    )
    defender = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="scout_cooldowns_received"
    )
    cooldown_until = models.DateTimeField("冷却截止时间")

    class Meta:
        verbose_name = "侦察冷却"
        verbose_name_plural = "侦察冷却"
        unique_together = ("attacker", "defender")
        indexes = [
            models.Index(fields=["attacker", "cooldown_until"]),
        ]

    def __str__(self) -> str:
        return f"{self.attacker.display_name} -> {self.defender.display_name} (冷却至 {self.cooldown_until})"

    @property
    def is_active(self) -> bool:
        """冷却是否仍在生效"""
        return self.cooldown_until > timezone.now()


class RaidRun(models.Model):
    """踢馆出征记录"""

    class Status(models.TextChoices):
        MARCHING = "marching", "行军中"
        BATTLING = "battling", "战斗中"
        RETURNING = "returning", "返程中"
        COMPLETED = "completed", "已完成"
        RETREATED = "retreated", "已撤退"

    attacker = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="raid_runs_sent",
        verbose_name="进攻方"
    )
    defender = models.ForeignKey(
        Manor,
        on_delete=models.CASCADE,
        related_name="raid_runs_received",
        verbose_name="防守方"
    )
    guests = models.ManyToManyField(
        "guests.Guest",
        related_name="raid_runs",
        blank=True,
        verbose_name="出征门客"
    )
    troop_loadout = models.JSONField("兵种配置", default=dict, blank=True)
    status = models.CharField(
        "状态",
        max_length=16,
        choices=Status.choices,
        default=Status.MARCHING
    )
    battle_report = models.ForeignKey(
        "battle.BattleReport",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raid_runs",
        verbose_name="战报"
    )

    # 时间相关
    travel_time = models.PositiveIntegerField("单程行军时间(秒)", default=0)
    started_at = models.DateTimeField("出发时间", auto_now_add=True)
    battle_at = models.DateTimeField("战斗时间", null=True, blank=True)
    return_at = models.DateTimeField("返程完成时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    # 战利品
    loot_resources = models.JSONField("掠夺资源", default=dict, blank=True)
    loot_items = models.JSONField("掠夺物品", default=dict, blank=True)

    # 声望变化
    attacker_prestige_change = models.IntegerField("进攻方声望变化", default=0)
    defender_prestige_change = models.IntegerField("防守方声望变化", default=0)

    # 撤退标记
    is_retreating = models.BooleanField("是否撤退中", default=False)

    # 战斗结果
    is_attacker_victory = models.BooleanField("进攻方是否胜利", null=True, blank=True)

    # 战斗通用奖励（经验果和装备回收）
    battle_rewards = models.JSONField("战斗奖励", default=dict, blank=True)

    class Meta:
        verbose_name = "踢馆出征"
        verbose_name_plural = "踢馆出征"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["attacker", "status", "-started_at"]),
            models.Index(fields=["defender", "status", "-started_at"]),
            models.Index(fields=["status", "battle_at"]),
            models.Index(fields=["status", "return_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.attacker.display_name} -> {self.defender.display_name} ({self.get_status_display()})"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        now = timezone.now()
        if self.status == self.Status.MARCHING:
            if self.battle_at:
                delta = self.battle_at - now
                return max(0, int(delta.total_seconds()))
        elif self.status == self.Status.RETURNING:
            if self.return_at:
                delta = self.return_at - now
                return max(0, int(delta.total_seconds()))
        return 0

    @property
    def can_retreat(self) -> bool:
        """是否可以撤退（仅在行军中且未开始撤退时可撤退）"""
        return self.status == self.Status.MARCHING and not self.is_retreating

    @property
    def next_state_at(self):
        """下一个状态的时间点（用于事件栏/倒计时显示）"""
        if self.status == self.Status.MARCHING:
            return self.battle_at
        if self.status in {self.Status.RETURNING, self.Status.RETREATED, self.Status.BATTLING}:
            return self.return_at
        return None

    @property
    def arrive_at(self):
        """兼容旧模板字段：预计到达时间（行军结束进入战斗时刻）"""
        return self.battle_at
