from django.contrib import admin
from .models import (
    Guild, GuildMember, GuildTechnology, GuildWarehouse,
    GuildExchangeLog, GuildApplication, GuildAnnouncement,
    GuildDonationLog, GuildResourceLog
)


@admin.register(Guild)
class GuildAdmin(admin.ModelAdmin):
    list_display = ['name', 'level', 'current_member_count', 'member_capacity', 'is_active', 'created_at']
    list_filter = ['level', 'is_active', 'auto_accept']
    search_fields = ['name', 'founder__username']
    readonly_fields = ['created_at']


@admin.register(GuildMember)
class GuildMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'guild', 'position', 'total_contribution', 'current_contribution', 'is_active']
    list_filter = ['position', 'is_active', 'joined_at']
    search_fields = ['user__username', 'guild__name']
    readonly_fields = ['joined_at', 'last_active_at']


@admin.register(GuildTechnology)
class GuildTechnologyAdmin(admin.ModelAdmin):
    list_display = ['guild', 'tech_key', 'category', 'level', 'max_level', 'last_production_at']
    list_filter = ['category', 'level']
    search_fields = ['guild__name', 'tech_key']


@admin.register(GuildWarehouse)
class GuildWarehouseAdmin(admin.ModelAdmin):
    list_display = ['guild', 'item_key', 'quantity', 'contribution_cost', 'total_produced', 'total_exchanged']
    list_filter = ['guild']
    search_fields = ['guild__name', 'item_key']


@admin.register(GuildExchangeLog)
class GuildExchangeLogAdmin(admin.ModelAdmin):
    list_display = ['guild', 'member', 'item_key', 'quantity', 'contribution_cost', 'exchanged_at']
    list_filter = ['exchanged_at']
    search_fields = ['guild__name', 'member__user__username', 'item_key']
    readonly_fields = ['exchanged_at']


@admin.register(GuildApplication)
class GuildApplicationAdmin(admin.ModelAdmin):
    list_display = ['guild', 'applicant', 'status', 'created_at', 'reviewed_by', 'reviewed_at']
    list_filter = ['status', 'created_at']
    search_fields = ['guild__name', 'applicant__username']
    readonly_fields = ['created_at', 'reviewed_at']


@admin.register(GuildAnnouncement)
class GuildAnnouncementAdmin(admin.ModelAdmin):
    list_display = ['guild', 'type', 'content', 'author', 'created_at']
    list_filter = ['type', 'created_at']
    search_fields = ['guild__name', 'content']
    readonly_fields = ['created_at']


@admin.register(GuildDonationLog)
class GuildDonationLogAdmin(admin.ModelAdmin):
    list_display = ['guild', 'member', 'resource_type', 'amount', 'contribution_gained', 'donated_at']
    list_filter = ['resource_type', 'donated_at']
    search_fields = ['guild__name', 'member__user__username']
    readonly_fields = ['donated_at']


@admin.register(GuildResourceLog)
class GuildResourceLogAdmin(admin.ModelAdmin):
    list_display = ['guild', 'action', 'silver_change', 'grain_change', 'gold_bar_change', 'related_user', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['guild__name', 'note']
    readonly_fields = ['created_at']

