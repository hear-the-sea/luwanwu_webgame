from django.contrib import admin

from ..models import ArenaEntry, ArenaEntryGuest, ArenaExchangeRecord, ArenaMatch, ArenaTournament


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
