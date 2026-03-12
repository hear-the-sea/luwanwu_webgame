import trade.services.market_service as market_service


def test_load_trade_market_rules_normalizes_yaml_payload(monkeypatch):
    market_service.clear_trade_market_rules_cache()
    monkeypatch.setattr(
        market_service,
        "load_yaml_data",
        lambda *args, **kwargs: {"listing_fees": {"7200": "6000", "bad": 1, "0": 10, "86400": 20000}},
    )
    market_service.clear_trade_market_rules_cache()

    loaded = market_service.load_trade_market_rules()

    assert loaded == {"listing_fees": {7200: 6000, 86400: 20000}}


def test_clear_trade_market_rules_cache_refreshes_listing_fees(monkeypatch):
    market_service.clear_trade_market_rules_cache()
    monkeypatch.setattr(
        market_service,
        "load_yaml_data",
        lambda *args, **kwargs: {"listing_fees": {7200: 7000, 28800: 12000}},
    )

    market_service.clear_trade_market_rules_cache()

    assert market_service.LISTING_FEES == {7200: 7000, 28800: 12000}
