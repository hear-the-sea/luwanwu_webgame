import json

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import format_html

from common.constants.resources import ResourceType
from core.admin_i18n import apply_common_field_labels

from .models import (
    ArenaEntry,
    ArenaEntryGuest,
    ArenaExchangeRecord,
    ArenaMatch,
    ArenaTournament,
    Building,
    BuildingType,
    GlobalMailCampaign,
    GlobalMailDelivery,
    InventoryItem,
    ItemTemplate,
    Manor,
    Message,
    MissionRun,
    MissionTemplate,
    RaidRun,
    ResourceEvent,
    ScoutCooldown,
    ScoutRecord,
    WorkAssignment,
    WorkTemplate,
)
from .services import create_message
from .tasks.global_mail import enqueue_global_mail_backfill

User = get_user_model()

apply_common_field_labels(
    Manor,
    BuildingType,
    Building,
    ResourceEvent,
    MissionTemplate,
    MissionRun,
    ItemTemplate,
    InventoryItem,
    GlobalMailCampaign,
    GlobalMailDelivery,
    Message,
    WorkTemplate,
    WorkAssignment,
    ArenaTournament,
    ArenaEntry,
    ArenaEntryGuest,
    ArenaMatch,
    ArenaExchangeRecord,
    ScoutRecord,
    ScoutCooldown,
    RaidRun,
    labels={
        "region": "地区",
        "prestige": "声望",
        "grain": "粮食",
        "silver": "银两",
        "arena_coins": "角斗币",
        "base_rate_per_hour": "基础时产",
        "rate_growth": "成长系数",
        "deliveries_count": "投递数量",
    },
)


@admin.register(Manor)
class ManorAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "name",
        "region",
        "coordinate_x",
        "coordinate_y",
        "prestige",
        "grain",
        "silver",
        "arena_coins",
    )
    list_filter = ("region",)
    search_fields = ("user__username", "user__email", "name")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "resource_updated_at", "last_active_at")
    fieldsets = (
        ("基本信息", {"fields": ("user", "name", "prestige", "prestige_silver_spent")}),
        ("位置信息", {"fields": ("region", "coordinate_x", "coordinate_y", "last_active_at")}),
        (
            "资源",
            {
                "fields": (
                    "grain",
                    "silver",
                    "arena_coins",
                    "grain_capacity",
                    "silver_capacity",
                    "storage_capacity",
                    "retainer_count",
                )
            },
        ),
        (
            "保护状态",
            {
                "fields": (
                    "newbie_protection_until",
                    "defeat_protection_until",
                    "peace_shield_until",
                    "last_relocation_at",
                ),
                "classes": ("collapse",),
            },
        ),
        ("时间", {"fields": ("created_at", "resource_updated_at"), "classes": ("collapse",)}),
    )


@admin.register(BuildingType)
class BuildingTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "resource_type", "base_rate_per_hour", "rate_growth")
    list_filter = ("resource_type",)
    search_fields = ("name", "key")


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("manor", "building_type", "level", "is_upgrading", "upgrade_complete_at")
    list_filter = ("building_type", "is_upgrading")


@admin.register(ResourceEvent)
class ResourceEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "manor_link",
        "resource_type_display",
        "delta_display",
        "reason_display",
        "note",
        "created_at",
    )
    list_filter = (
        "resource_type",
        "reason",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("manor__user__username", "manor__name", "note")
    readonly_fields = ("manor", "resource_type", "delta", "reason", "note", "created_at")
    date_hierarchy = "created_at"
    list_per_page = 50
    ordering = ("-created_at",)

    # 禁止添加和修改（流水记录只读）
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def manor_link(self, obj):
        """显示庄园链接"""
        from django.urls import reverse
        from django.utils.html import format_html

        url = reverse("admin:gameplay_manor_change", args=[obj.manor_id])
        return format_html('<a href="{}">{}</a>', url, obj.manor.name or obj.manor.user.username)

    manor_link.short_description = "庄园"
    manor_link.admin_order_field = "manor__user__username"

    def resource_type_display(self, obj):
        """资源类型中文显示"""
        labels = dict(ResourceType.choices)
        icons = {"grain": "🌾", "silver": "💰"}
        label = labels.get(obj.resource_type, obj.resource_type)
        icon = icons.get(obj.resource_type, "")
        return f"{icon} {label}".strip()

    resource_type_display.short_description = "资源类型"
    resource_type_display.admin_order_field = "resource_type"

    def delta_display(self, obj):
        """数量显示（带颜色）"""
        from django.utils.html import format_html

        if obj.delta > 0:
            return format_html('<span style="color: green;">+{}</span>', obj.delta)
        elif obj.delta < 0:
            return format_html('<span style="color: red;">{}</span>', obj.delta)
        return obj.delta

    delta_display.short_description = "变化量"
    delta_display.admin_order_field = "delta"

    def reason_display(self, obj):
        """原因中文显示"""
        reason_map = {
            "produce": "🌾 自动产出",
            "upgrade_cost": "🏗️ 建筑升级",
            "task_reward": "🎁 任务奖励",
            "battle_reward": "⚔️ 战斗掉落",
            "admin_adjust": "⚙️ 运营调整",
            "recruit_cost": "👥 门客招募",
            "training_cost": "📖 门客培养",
            "item_use": "🎒 道具使用",
            "shop_purchase": "🛒 商铺购买",
            "shop_sell": "💵 商铺出售",
            "work_reward": "💼 打工报酬",
            "guild_donation": "🏛️ 帮会捐献",
            "market_listing_fee": "📋 交易行挂单手续费",
            "market_purchase": "🛍️ 交易行购买",
            "market_sold": "💰 交易行出售",
            "item_sold": "📦 物品出售",
            "tech_upgrade": "📚 科技升级",
        }
        return reason_map.get(obj.reason, obj.reason)

    reason_display.short_description = "原因"
    reason_display.admin_order_field = "reason"


@admin.register(MissionTemplate)
class MissionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "battle_type", "daily_limit", "base_travel_time")
    search_fields = ("name", "key")


@admin.register(MissionRun)
class MissionRunAdmin(admin.ModelAdmin):
    list_display = ("mission", "manor", "status", "started_at", "return_at")
    list_filter = ("status",)


@admin.register(ItemTemplate)
class ItemTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "effect_type", "rarity", "tradeable", "price")
    list_filter = ("effect_type", "rarity", "tradeable")
    search_fields = ("name", "key")
    ordering = ("effect_type", "rarity", "name")


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("manor", "template", "quantity", "updated_at")
    list_filter = ("template__effect_type", "template__rarity")
    search_fields = ("manor__user__username", "template__name")
    autocomplete_fields = ("manor", "template")


class SendMessageForm(forms.ModelForm):
    """发送消息的自定义表单"""

    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=admin.widgets.FilteredSelectMultiple("玩家", False),
        label="指定玩家（不选则发送给所有人）",
        help_text="按住 Ctrl 多选",
    )

    attachment_resources = forms.JSONField(
        required=False,
        initial={},
        label="附件资源",
        help_text='格式：{"grain": 100, "silver": 200}',
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
    )

    attachment_items = forms.JSONField(
        required=False,
        initial={},
        label="附件道具",
        help_text='格式：{"item_key": 数量}，例如：{"experience_peach": 5}',
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
    )

    class Meta:
        model = Message
        fields = ["kind", "title", "body"]


class GlobalMailCampaignForm(forms.ModelForm):
    attachment_resources = forms.JSONField(
        required=False,
        initial={},
        label="附件资源",
        help_text='格式：{"grain": 100, "silver": 200}',
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
    )
    attachment_items = forms.JSONField(
        required=False,
        initial={},
        label="附件道具",
        help_text='格式：{"item_key": 数量}，例如：{"peace_shield_small": 1}',
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
    )
    send_to_existing_now = forms.BooleanField(
        required=False,
        label="保存后补发给现有玩家",
        help_text="仅补发当前生效活动，已收到过的玩家不会重复收到。",
    )
    backfill_batch_size = forms.IntegerField(
        required=False,
        min_value=50,
        max_value=5000,
        initial=500,
        label="补发批大小",
        help_text="仅在勾选“保存后补发给现有玩家”时生效，推荐 200~1000。",
    )

    class Meta:
        model = GlobalMailCampaign
        fields = ["key", "kind", "title", "body", "is_active", "start_at", "end_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attachments = self.instance.attachments if getattr(self.instance, "pk", None) else {}
        if isinstance(attachments, dict):
            self.fields["attachment_resources"].initial = attachments.get("resources") or {}
            self.fields["attachment_items"].initial = attachments.get("items") or {}

    @staticmethod
    def _normalize_attachment_bucket(value, field_name: str) -> dict[str, int]:
        bucket = value or {}
        if not isinstance(bucket, dict):
            raise forms.ValidationError({field_name: f"{field_name} 必须为对象"})

        normalized: dict[str, int] = {}
        for raw_key, raw_amount in bucket.items():
            key = str(raw_key).strip()
            if not key:
                raise forms.ValidationError({field_name: f"{field_name} 的 key 必须为非空字符串"})
            try:
                amount = int(raw_amount)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError({field_name: f"{field_name}.{key} 必须为整数"}) from exc
            if amount <= 0:
                raise forms.ValidationError({field_name: f"{field_name}.{key} 必须大于 0"})
            normalized[key] = amount
        return normalized

    def clean(self):
        cleaned_data = super().clean()
        resources = self._normalize_attachment_bucket(cleaned_data.get("attachment_resources"), "attachment_resources")
        items = self._normalize_attachment_bucket(cleaned_data.get("attachment_items"), "attachment_items")

        attachments = {}
        if resources:
            attachments["resources"] = resources
        if items:
            attachments["items"] = items
        cleaned_data["attachments"] = attachments
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.attachments = self.cleaned_data.get("attachments", {})
        if commit:
            instance.save()
        return instance


class CampaignRuntimeStatusFilter(admin.SimpleListFilter):
    title = "运行状态"
    parameter_name = "runtime_status"

    def lookups(self, request, model_admin):
        return (
            ("active", "进行中"),
            ("pending", "未开始"),
            ("ended", "已结束"),
            ("inactive", "已停用"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        value = self.value()
        if value == "inactive":
            return queryset.filter(is_active=False)
        if value == "pending":
            return queryset.filter(is_active=True, start_at__isnull=False, start_at__gt=now)
        if value == "active":
            return (
                queryset.filter(is_active=True)
                .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
                .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
            )
        if value == "ended":
            return queryset.filter(is_active=True, end_at__isnull=False, end_at__lt=now)
        return queryset


@admin.register(GlobalMailCampaign)
class GlobalMailCampaignAdmin(admin.ModelAdmin):
    form = GlobalMailCampaignForm
    list_display = (
        "key",
        "title",
        "kind",
        "runtime_status_badge",
        "is_active",
        "start_at",
        "end_at",
        "attachments_summary",
        "deliveries_count",
        "created_at",
    )
    list_filter = ("kind", "is_active", CampaignRuntimeStatusFilter)
    search_fields = ("key", "title", "body")
    readonly_fields = ("runtime_status_badge", "attachments_preview", "deliveries_count", "created_at", "updated_at")
    date_hierarchy = "created_at"
    save_on_top = True
    actions = ["backfill_selected_campaigns", "activate_selected_campaigns", "deactivate_selected_campaigns"]
    fieldsets = (
        ("基础信息", {"fields": ("key", "kind", "title", "body", "runtime_status_badge")}),
        ("生效时间", {"fields": ("is_active", "start_at", "end_at")}),
        ("附件配置", {"fields": ("attachment_resources", "attachment_items", "attachments_preview")}),
        ("补发操作", {"fields": ("send_to_existing_now", "backfill_batch_size")}),
        ("统计", {"fields": ("deliveries_count", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_deliveries_count=Count("deliveries"))

    def deliveries_count(self, obj):
        if obj is None or not getattr(obj, "pk", None):
            return 0
        return int(getattr(obj, "_deliveries_count", obj.deliveries.count()))

    deliveries_count.short_description = "已投递"
    deliveries_count.admin_order_field = "_deliveries_count"

    def runtime_status_badge(self, obj):
        if obj is None or not getattr(obj, "pk", None):
            return format_html('<span style="color:#6b7280;">{}</span>', "未保存")
        now = timezone.now()
        if not obj.is_active:
            return format_html('<span style="color:#6b7280;">{}</span>', "已停用")
        if obj.start_at and obj.start_at > now:
            return format_html('<span style="color:#d97706;">{}</span>', "未开始")
        if obj.end_at and obj.end_at < now:
            return format_html('<span style="color:#2563eb;">{}</span>', "已结束")
        return format_html('<span style="color:#059669;font-weight:600;">{}</span>', "进行中")

    runtime_status_badge.short_description = "运行状态"

    def attachments_summary(self, obj):
        attachments = obj.attachments if isinstance(obj.attachments, dict) else {}
        resources = attachments.get("resources") if isinstance(attachments.get("resources"), dict) else {}
        items = attachments.get("items") if isinstance(attachments.get("items"), dict) else {}
        resource_total = sum(int(v) for v in resources.values()) if resources else 0
        item_total = sum(int(v) for v in items.values()) if items else 0
        if not resources and not items:
            return "无附件"
        return f"资源 {len(resources)} 类/{resource_total}，道具 {len(items)} 类/{item_total}"

    attachments_summary.short_description = "附件摘要"

    def attachments_preview(self, obj):
        attachments = obj.attachments if obj and isinstance(obj.attachments, dict) else {}
        pretty = json.dumps(attachments or {}, ensure_ascii=False, indent=2)
        return format_html("<pre style='max-width:760px;white-space:pre-wrap;'>{}</pre>", pretty)

    attachments_preview.short_description = "附件预览"

    @admin.action(description="批量启用活动")
    def activate_selected_campaigns(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个活动")

    @admin.action(description="批量停用活动")
    def deactivate_selected_campaigns(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个活动")

    @admin.action(description="补发给当前所有玩家（幂等）")
    def backfill_selected_campaigns(self, request, queryset):
        queued = 0
        for campaign in queryset:
            async_result = enqueue_global_mail_backfill(campaign.id)
            queued += 1
            self.message_user(request, f"活动 {campaign.key} 已提交补发任务（task_id={async_result.id}）")
        if queued > 1:
            self.message_user(request, f"已提交 {queued} 个补发任务")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.cleaned_data.get("send_to_existing_now"):
            batch_size = int(form.cleaned_data.get("backfill_batch_size") or 500)
            async_result = enqueue_global_mail_backfill(obj.id, batch_size=batch_size)
            self.message_user(
                request,
                f"已提交补发任务（task_id={async_result.id}，batch_size={batch_size}）",
            )


@admin.register(GlobalMailDelivery)
class GlobalMailDeliveryAdmin(admin.ModelAdmin):
    list_display = ("campaign", "manor", "message", "created_at")
    list_filter = ("campaign", ("created_at", admin.DateFieldListFilter))
    search_fields = ("campaign__key", "campaign__title", "manor__user__username", "manor__name", "message__title")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("campaign", "manor", "message")
    list_select_related = ("campaign", "manor__user", "message")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    def has_add_permission(self, request):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("title", "manor", "kind", "has_attachments", "is_claimed", "is_read", "created_at")
    list_filter = ("kind", "is_read", "is_claimed", "created_at")
    search_fields = ("title", "body", "manor__user__username")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("manor",)

    def has_attachments(self, obj):
        return obj.has_attachments

    has_attachments.boolean = True
    has_attachments.short_description = "有附件"

    def get_form(self, request, obj=None, **kwargs):
        """为添加消息使用自定义表单"""
        if obj is None:  # 只在创建时使用自定义表单
            kwargs["form"] = SendMessageForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        """保存消息时处理批量发送和附件"""
        if change:  # 编辑现有消息
            super().save_model(request, obj, form, change)
            return

        # 新建消息 - 批量发送
        recipients = form.cleaned_data.get("recipients")
        attachment_resources = form.cleaned_data.get("attachment_resources") or {}
        attachment_items = form.cleaned_data.get("attachment_items") or {}

        # 构建附件数据
        attachments = {}
        if attachment_resources:
            attachments["resources"] = attachment_resources
        if attachment_items:
            attachments["items"] = attachment_items

        # 如果没有指定接收人，发送给所有人
        if not recipients:
            recipients = User.objects.filter(is_active=True)

        # 批量创建消息
        for user in recipients:
            manor = Manor.objects.filter(user=user).first()
            if manor:
                create_message(
                    manor=manor,
                    kind=obj.kind,
                    title=obj.title,
                    body=obj.body,
                    attachments=attachments if attachments else None,
                )

        # 显示成功消息
        self.message_user(request, f"已向 {recipients.count()} 位玩家发送消息")

    @admin.action(description="标记为已读")
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)
        self.message_user(request, f"已标记 {queryset.count()} 条消息为已读")

    @admin.action(description="标记为未读")
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)
        self.message_user(request, f"已标记 {queryset.count()} 条消息为未读")

    actions = ["mark_as_read", "mark_as_unread"]


@admin.register(WorkTemplate)
class WorkTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "tier", "required_level", "reward_silver", "work_duration", "display_order")
    list_filter = ("tier",)
    search_fields = ("name", "key")
    ordering = ("tier", "display_order", "required_level")


@admin.register(WorkAssignment)
class WorkAssignmentAdmin(admin.ModelAdmin):
    list_display = ("guest", "work_template", "manor", "status", "started_at", "complete_at", "reward_claimed")
    list_filter = ("status", "reward_claimed")
    search_fields = ("guest__name", "manor__user__username")
    autocomplete_fields = ("manor", "guest", "work_template")
    readonly_fields = ("started_at", "complete_at", "finished_at")
    date_hierarchy = "started_at"


@admin.register(ArenaTournament)
class ArenaTournamentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "player_limit",
        "current_round",
        "next_round_at",
        "started_at",
        "ended_at",
        "winner_entry",
    )
    list_filter = ("status",)
    search_fields = ("id", "winner_entry__manor__name", "winner_entry__manor__user__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ArenaEntry)
class ArenaEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "tournament", "manor", "status", "final_rank", "coin_reward", "joined_at")
    list_filter = ("status", "final_rank")
    search_fields = ("manor__name", "manor__user__username", "tournament__id")
    autocomplete_fields = ("tournament", "manor")


@admin.register(ArenaEntryGuest)
class ArenaEntryGuestAdmin(admin.ModelAdmin):
    list_display = ("id", "entry", "guest", "created_at")
    search_fields = ("entry__id", "guest__template__name", "guest__manor__user__username")
    autocomplete_fields = ("entry", "guest")


@admin.register(ArenaMatch)
class ArenaMatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tournament",
        "round_number",
        "match_index",
        "attacker_entry",
        "defender_entry",
        "winner_entry",
        "status",
        "battle_report",
    )
    list_filter = ("status", "round_number")
    search_fields = ("tournament__id", "attacker_entry__manor__user__username", "defender_entry__manor__user__username")
    autocomplete_fields = ("tournament", "attacker_entry", "defender_entry", "winner_entry")


@admin.register(ArenaExchangeRecord)
class ArenaExchangeRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "manor", "reward_key", "reward_name", "cost_coins", "quantity", "created_at")
    list_filter = ("reward_key",)
    search_fields = ("manor__name", "manor__user__username", "reward_key", "reward_name")
    autocomplete_fields = ("manor",)


# ============ PVP 踢馆系统 Admin ============


@admin.register(ScoutRecord)
class ScoutRecordAdmin(admin.ModelAdmin):
    list_display = ("attacker", "defender", "status", "success_rate", "started_at", "complete_at")
    list_filter = ("status",)
    search_fields = ("attacker__user__username", "defender__user__username")
    readonly_fields = ("started_at", "completed_at", "intel_data")
    date_hierarchy = "started_at"


@admin.register(ScoutCooldown)
class ScoutCooldownAdmin(admin.ModelAdmin):
    list_display = ("attacker", "defender", "cooldown_until", "is_active")
    search_fields = ("attacker__user__username", "defender__user__username")

    def is_active(self, obj):
        return obj.is_active

    is_active.boolean = True
    is_active.short_description = "冷却中"


@admin.register(RaidRun)
class RaidRunAdmin(admin.ModelAdmin):
    list_display = ("attacker", "defender", "status", "is_attacker_victory", "started_at", "battle_at", "return_at")
    list_filter = ("status", "is_attacker_victory")
    search_fields = ("attacker__user__username", "defender__user__username")
    readonly_fields = (
        "started_at",
        "battle_at",
        "return_at",
        "completed_at",
        "loot_resources",
        "loot_items",
        "attacker_prestige_change",
        "defender_prestige_change",
    )
    date_hierarchy = "started_at"
    filter_horizontal = ("guests",)
