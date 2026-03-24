import gameplay.services.buildings.ranch as ranch_service


def test_load_ranch_production_config_normalizes_yaml_payload(monkeypatch):
    ranch_service.clear_ranch_production_cache()
    monkeypatch.setattr(
        ranch_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "test_livestock": {
                    "grain_cost": "80",
                    "base_duration": "200",
                    "required_animal_husbandry": "4",
                }
            }
        },
    )
    ranch_service.clear_ranch_production_cache()

    loaded = ranch_service.load_ranch_production_config()

    assert loaded == {
        "test_livestock": {
            "grain_cost": 80,
            "base_duration": 200,
            "required_animal_husbandry": 4,
        }
    }


def test_load_ranch_production_config_rejects_invalid_entry(monkeypatch):
    ranch_service.clear_ranch_production_cache()
    monkeypatch.setattr(
        ranch_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "bad_livestock": {
                    "grain_cost": 80,
                    "base_duration": "bad",
                    "required_animal_husbandry": 4,
                }
            }
        },
    )
    ranch_service.load_ranch_production_config.cache_clear()

    try:
        with __import__("pytest").raises(AssertionError, match="invalid ranch production base_duration"):
            ranch_service.load_ranch_production_config()
    finally:
        monkeypatch.undo()
        ranch_service.clear_ranch_production_cache()


def test_clear_ranch_production_cache_refreshes_global_livestock_config(monkeypatch):
    ranch_service.clear_ranch_production_cache()
    monkeypatch.setattr(
        ranch_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "refresh_livestock": {
                    "grain_cost": 90,
                    "base_duration": 210,
                    "required_animal_husbandry": 5,
                }
            }
        },
    )

    ranch_service.clear_ranch_production_cache()

    assert ranch_service.LIVESTOCK_CONFIG == {
        "refresh_livestock": {
            "grain_cost": 90,
            "base_duration": 210,
            "required_animal_husbandry": 5,
        }
    }
