from django.contrib import admin

from core.admin_i18n import apply_common_field_labels

from .models import BattleReport, TroopTemplate

apply_common_field_labels(TroopTemplate, BattleReport)


@admin.register(TroopTemplate)
class TroopTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "base_attack", "base_defense", "base_hp", "priority")
    list_filter = ("priority",)
    search_fields = ("name", "key", "description")
    ordering = ("priority", "key")


@admin.register(BattleReport)
class BattleReportAdmin(admin.ModelAdmin):
    list_display = ("manor", "opponent_name", "battle_type", "winner", "starts_at", "completed_at")
    list_filter = ("winner", "battle_type")
