import gameplay.services.buildings.smithy as smithy_service


def test_load_smithy_production_config_normalizes_yaml_payload(monkeypatch):
    smithy_service.clear_smithy_production_cache()
    monkeypatch.setattr(
        smithy_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "tong": {
                    "cost_type": "silver",
                    "cost_amount": "2",
                    "base_duration": "90",
                    "required_smelting": "1",
                    "category": "metal",
                },
            }
        },
    )
    smithy_service.clear_smithy_production_cache()

    loaded = smithy_service.load_smithy_production_config()

    assert loaded == {
        "tong": {
            "cost_type": "silver",
            "cost_amount": 2,
            "base_duration": 90,
            "required_smelting": 1,
            "category": "metal",
        }
    }


def test_load_smithy_production_config_rejects_invalid_entry(monkeypatch):
    smithy_service.clear_smithy_production_cache()
    monkeypatch.setattr(
        smithy_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "bad_metal": {
                    "cost_type": "silver",
                    "cost_amount": 2,
                    "base_duration": 90,
                    "required_smelting": 1,
                    "category": True,
                }
            }
        },
    )
    smithy_service.load_smithy_production_config.cache_clear()

    try:
        with __import__("pytest").raises(AssertionError, match="invalid smithy production category"):
            smithy_service.load_smithy_production_config()
    finally:
        monkeypatch.undo()
        smithy_service.clear_smithy_production_cache()


def test_clear_smithy_production_cache_refreshes_global_metal_config(monkeypatch):
    smithy_service.clear_smithy_production_cache()
    monkeypatch.setattr(
        smithy_service,
        "load_yaml_data",
        lambda *args, **kwargs: {
            "production": {
                "test_medicine": {
                    "cost_type": "silver",
                    "cost_amount": 30,
                    "base_duration": 300,
                    "required_smithy": 2,
                    "category": "medicine",
                }
            }
        },
    )

    smithy_service.clear_smithy_production_cache()

    assert smithy_service.METAL_CONFIG == {
        "test_medicine": {
            "cost_type": "silver",
            "cost_amount": 30,
            "base_duration": 300,
            "required_smithy": 2,
            "category": "medicine",
        }
    }
