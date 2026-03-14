import gameplay.services.buildings.forge as forge_service


def test_load_forge_equipment_config_normalizes_yaml_payload(monkeypatch):
    forge_service.clear_forge_equipment_cache()
    monkeypatch.setattr(
        forge_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "equipment": {
                "equip_test": {
                    "category": "helmet",
                    "materials": {"tong": "3", "": 2, "xi": 0},
                    "base_duration": "120",
                    "required_forging": "2",
                },
                "invalid_missing_category": {
                    "materials": {"tong": 1},
                },
            }
        },
    )

    forge_service.clear_forge_equipment_cache()
    loaded = forge_service.load_forge_equipment_config()

    assert loaded == {
        "equip_test": {
            "category": "helmet",
            "materials": {"tong": 3},
            "base_duration": 120,
            "required_forging": 2,
        }
    }


def test_clear_forge_equipment_cache_refreshes_global_equipment_config(monkeypatch):
    forge_service.clear_forge_equipment_cache()
    monkeypatch.setattr(
        forge_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "equipment": {
                "equip_refresh": {
                    "category": "armor",
                    "materials": {"tie": 5},
                    "base_duration": 180,
                    "required_forging": 3,
                }
            }
        },
    )

    forge_service.clear_forge_equipment_cache()

    assert forge_service.EQUIPMENT_CONFIG == {
        "equip_refresh": {
            "category": "armor",
            "materials": {"tie": 5},
            "base_duration": 180,
            "required_forging": 3,
        }
    }


def test_load_forge_equipment_config_includes_advanced_helmets():
    forge_service.clear_forge_equipment_cache()

    loaded = forge_service.load_forge_equipment_config()

    assert loaded["equip_yulindin"] == {
        "category": "helmet",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    }
    assert loaded["equip_baihongkui"] == {
        "category": "helmet",
        "materials": {"tie": 30},
        "base_duration": 360,
        "required_forging": 9,
    }
