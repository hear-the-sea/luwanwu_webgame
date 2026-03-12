from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_TRADE_MARKET_RULES: dict[str, Any] = {"listing_fees": {7200: 5000, 28800: 10000, 86400: 20000}}


def normalize_trade_market_rules(raw: Any) -> dict[str, dict[int, int]]:
    listing_fees_raw = raw.get("listing_fees") if isinstance(raw, dict) else None
    if not isinstance(listing_fees_raw, dict):
        listing_fees_raw = DEFAULT_TRADE_MARKET_RULES["listing_fees"]

    listing_fees: dict[int, int] = {}
    for raw_duration, raw_fee in listing_fees_raw.items():
        try:
            duration = int(raw_duration)
            fee = int(raw_fee)
        except (TypeError, ValueError):
            continue
        if duration <= 0 or fee < 0:
            continue
        listing_fees[duration] = fee

    if not listing_fees:
        listing_fees = dict(DEFAULT_TRADE_MARKET_RULES["listing_fees"])
    return {"listing_fees": listing_fees}


def build_trade_market_rules_loader(*, rules_path: Path, logger, load_yaml_data_func):
    @lru_cache(maxsize=1)
    def _load_trade_market_rules() -> dict[str, dict[int, int]]:
        raw = load_yaml_data_func(
            rules_path,
            logger=logger,
            context="trade market rules",
            default=DEFAULT_TRADE_MARKET_RULES,
        )
        return normalize_trade_market_rules(raw)

    return _load_trade_market_rules
