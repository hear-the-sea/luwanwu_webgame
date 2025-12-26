from django.contrib import admin

from .models import BattleReport, TroopTemplate


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
