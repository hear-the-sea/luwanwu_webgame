import gameplay.services.buildings.stable as stable_service


def test_load_stable_production_config_normalizes_yaml_payload(monkeypatch):
    stable_service.clear_stable_production_cache()
    monkeypatch.setattr(
        stable_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "equip_test_horse": {
                    "grain_cost": "600",
                    "base_duration": "180",
                    "required_horsemanship": "2",
                }
            }
        },
    )
    stable_service.clear_stable_production_cache()

    loaded = stable_service.load_stable_production_config()

    assert loaded == {
        "equip_test_horse": {
            "grain_cost": 600,
            "base_duration": 180,
            "required_horsemanship": 2,
        }
    }


def test_load_stable_production_config_rejects_invalid_entry(monkeypatch):
    stable_service.clear_stable_production_cache()
    monkeypatch.setattr(
        stable_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "equip_bad_horse": {
                    "grain_cost": True,
                    "base_duration": 180,
                    "required_horsemanship": 2,
                }
            }
        },
    )
    stable_service.load_stable_production_config.cache_clear()

    try:
        with __import__("pytest").raises(AssertionError, match="invalid stable production grain_cost"):
            stable_service.load_stable_production_config()
    finally:
        monkeypatch.undo()
        stable_service.clear_stable_production_cache()


def test_clear_stable_production_cache_refreshes_global_horse_config(monkeypatch):
    stable_service.clear_stable_production_cache()
    monkeypatch.setattr(
        stable_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "equip_refresh_horse": {
                    "grain_cost": 700,
                    "base_duration": 240,
                    "required_horsemanship": 3,
                }
            }
        },
    )

    stable_service.clear_stable_production_cache()

    assert stable_service.HORSE_CONFIG == {
        "equip_refresh_horse": {
            "grain_cost": 700,
            "base_duration": 240,
            "required_horsemanship": 3,
        }
    }
