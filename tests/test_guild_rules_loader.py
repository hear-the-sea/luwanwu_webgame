from guilds.constants import DEFAULT_GUILD_RULES, clear_guild_rules_cache, load_guild_rules, normalize_guild_rules


def test_normalize_guild_rules_uses_defaults_for_invalid_root():
    assert normalize_guild_rules(["invalid-root"]) == DEFAULT_GUILD_RULES


def test_normalize_guild_rules_merges_and_clamps_values():
    loaded = normalize_guild_rules(
        {
            "pagination": {"guild_list_page_size": "30"},
            "creation": {"guild_creation_cost": {"gold_bar": "3"}, "guild_upgrade_base_cost": "8"},
            "contribution": {
                "rates": {"silver": "2"},
                "daily_limits": {"grain": "60000"},
                "min_donation_amount": "200",
            },
            "technology": {
                "upgrade_costs": {"equipment_forge": {"silver": "6000", "grain": 2500, "gold_bar": 2}},
                "names": {"equipment_forge": "新装备锻造"},
            },
            "warehouse": {
                "exchange_costs": {"gear_green": "60"},
                "daily_exchange_limit": "12",
            },
            "hero_pool": {
                "slot_limit": "3",
                "battle_lineup_limit": "25",
                "replace_cooldown_seconds": "1200",
            },
        }
    )

    assert loaded["pagination"]["guild_list_page_size"] == 30
    assert loaded["creation"]["guild_creation_cost"]["gold_bar"] == 3
    assert loaded["creation"]["guild_upgrade_base_cost"] == 8
    assert loaded["contribution"]["rates"]["silver"] == 2
    assert loaded["contribution"]["daily_limits"]["grain"] == 60000
    assert loaded["contribution"]["min_donation_amount"] == 200
    assert loaded["technology"]["upgrade_costs"]["equipment_forge"]["silver"] == 6000
    assert loaded["technology"]["names"]["equipment_forge"] == "新装备锻造"
    assert loaded["warehouse"]["exchange_costs"]["gear_green"] == 60
    assert loaded["warehouse"]["daily_exchange_limit"] == 12
    assert loaded["hero_pool"]["slot_limit"] == 3
    assert loaded["hero_pool"]["battle_lineup_limit"] == 25
    assert loaded["hero_pool"]["replace_cooldown_seconds"] == 1200


def test_load_guild_rules_reads_yaml_via_cache(monkeypatch):
    clear_guild_rules_cache()
    monkeypatch.setattr(
        "guilds.constants.load_yaml_data",
        lambda *args, **kwargs: {
            "pagination": {"guild_hall_display_limit": 9},
            "warehouse": {"daily_exchange_limit": 7},
        },
    )

    loaded = load_guild_rules()

    assert loaded["pagination"]["guild_hall_display_limit"] == 9
    assert loaded["warehouse"]["daily_exchange_limit"] == 7
