from __future__ import annotations

from django.db import models

from .manor import ResourceType


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
        BANK_EXCHANGE = "bank_exchange", "钱庄兑换"
        SHOP_PURCHASE = "shop_purchase", "商铺购买"
        SHOP_SELL = "shop_sell", "商铺出售"
        WORK_REWARD = "work_reward", "打工报酬"
        GUILD_DONATION = "guild_donation", "帮会捐献"
        MARKET_LISTING_FEE = "market_listing_fee", "交易行挂单手续费"
        MARKET_PURCHASE = "market_purchase", "交易行购买"
        MARKET_SOLD = "market_sold", "交易行出售"
        ITEM_SOLD = "item_sold", "物品出售"
        TECH_UPGRADE = "tech_upgrade", "科技升级"

    manor = models.ForeignKey("gameplay.Manor", on_delete=models.CASCADE, related_name="resource_events")
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
        LOOT_BOX = "loot_box", "宝箱"

    key = models.SlugField(unique=True)
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True)
    effect_type = models.CharField(max_length=32, choices=EffectType.choices, default=EffectType.RESOURCE_PACK)
    effect_payload = models.JSONField(default=dict, blank=True)
    icon = models.CharField(max_length=32, blank=True)
    image = models.ImageField(upload_to="items/", blank=True, null=True, verbose_name="物品图片")
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


_ITEM_EFFECT_STAT_LABELS = {
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


def _resource_pack_summary(payload: dict) -> str:
    labels = dict(ResourceType.choices)
    parts = [f"{labels.get(key, key)} +{amount}" for key, amount in payload.items()]
    return "、".join(parts)


def _equipment_set_summary(payload: dict) -> str:
    set_desc = payload.get("set_description")
    set_bonus = payload.get("set_bonus") or {}
    if not (set_desc or set_bonus):
        return ""

    pieces = set_bonus.get("pieces") if isinstance(set_bonus, dict) else None
    bonus_map = set_bonus.get("bonus") if isinstance(set_bonus, dict) else None
    bonus_parts = []
    if isinstance(bonus_map, dict):
        for key, value in bonus_map.items():
            if value is None:
                continue
            bonus_parts.append(f"{_ITEM_EFFECT_STAT_LABELS.get(key, key)}+{value}")

    desc_text = set_desc or "套装"
    piece_text = f"（{pieces}件）" if pieces else ""
    if bonus_parts:
        return f"{desc_text}{piece_text}：" + "、".join(bonus_parts)
    return f"{desc_text}{piece_text}"


def _equipment_summary(payload: dict) -> str:
    parts = []
    for key, value in payload.items():
        if value is None or key in {"set_key", "set_bonus", "set_description"}:
            continue
        parts.append(f"{_ITEM_EFFECT_STAT_LABELS.get(key, key)}+{value}")

    set_text = _equipment_set_summary(payload)
    if set_text:
        return ("、".join(parts) + "；" if parts else "") + set_text
    return "、".join(parts) or "提升属性"


def _tool_summary(template_key: str, payload: dict) -> str:
    if template_key == "fangdajing":
        return "显现候选稀有度"
    if template_key.startswith("peace_shield_"):
        duration = payload.get("duration")
        if not duration:
            return "免战保护"
        hours = duration // 3600
        if hours % 24 == 0:
            return f"免战保护 {hours // 24} 天"
        return f"免战保护 {hours} 小时"
    if template_key == "manor_rename_card":
        return "更换庄园名称"
    return "道具"


class InventoryItem(models.Model):
    class StorageLocation(models.TextChoices):
        WAREHOUSE = "warehouse", "仓库"
        TREASURY = "treasury", "藏宝阁"

    manor = models.ForeignKey("gameplay.Manor", on_delete=models.CASCADE, related_name="inventory_items")
    template = models.ForeignKey(ItemTemplate, on_delete=models.CASCADE, related_name="inventory_entries")
    quantity = models.PositiveIntegerField(default=0)
    storage_location = models.CharField(
        max_length=16,
        choices=StorageLocation.choices,
        default=StorageLocation.WAREHOUSE,
        verbose_name="存储位置",
    )
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
            return _resource_pack_summary(payload)
        if effect_type == ItemTemplate.EffectType.SKILL_BOOK:
            skill_name = payload.get("skill_name") or payload.get("skill_key", "技能")
            return f"学习 {skill_name}"
        if effect_type and effect_type.startswith("equip_"):
            return _equipment_summary(payload)
        if effect_type == ItemTemplate.EffectType.MEDICINE:
            hp = payload.get("hp")
            if hp:
                return f"恢复生命 +{hp}"
            return "恢复生命"
        if effect_type == ItemTemplate.EffectType.TOOL:
            return _tool_summary(self.template.key or "", payload)
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

    manor = models.ForeignKey("gameplay.Manor", on_delete=models.CASCADE, related_name="messages")
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
