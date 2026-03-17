from __future__ import annotations

from typing import Any

from .bank_flows import build_bank_info_payload, execute_gold_bar_exchange


def exchange_gold_bar_entry(manor: Any, quantity: int, *, service_module: Any) -> dict[str, Any]:
    return execute_gold_bar_exchange(
        manor,
        quantity,
        transaction_atomic=getattr(service_module, "transaction").atomic,
        manor_model=getattr(service_module, "Manor"),
        normalize_positive_quantity=getattr(service_module, "_normalize_positive_quantity"),
        calculate_gold_bar_cost=getattr(service_module, "calculate_gold_bar_cost"),
        spend_exchange_cost_locked=getattr(service_module, "_spend_exchange_cost_locked"),
        grant_gold_bars_locked=getattr(service_module, "_grant_gold_bars_locked"),
        record_gold_bar_exchange_locked=getattr(service_module, "_record_gold_bar_exchange_locked"),
        clear_supply_cache=lambda: getattr(service_module, "_safe_cache_delete")(
            getattr(service_module, "SUPPLY_CACHE_KEY")
        ),
        build_exchange_result=getattr(service_module, "_build_exchange_result"),
    )


def get_bank_info_entry(manor: Any, *, service_module: Any) -> dict[str, Any]:
    return build_bank_info_payload(
        manor,
        get_effective_gold_supply_data=getattr(service_module, "_get_effective_gold_supply_data"),
        resolve_pricing_status=getattr(service_module, "_resolve_pricing_status"),
        get_today_exchange_count=getattr(service_module, "get_today_exchange_count"),
        calculate_supply_factor_from_supply=getattr(service_module, "_calculate_supply_factor_from_supply"),
        calculate_dynamic_rate=getattr(service_module, "calculate_dynamic_rate"),
        calculate_next_rate=getattr(service_module, "calculate_next_rate"),
        calculate_progressive_factor=getattr(service_module, "calculate_progressive_factor"),
        calculate_gold_bar_cost=getattr(service_module, "calculate_gold_bar_cost"),
        gold_bar_base_price=getattr(service_module, "GOLD_BAR_BASE_PRICE"),
        gold_bar_fee_rate=getattr(service_module, "GOLD_BAR_FEE_RATE"),
        gold_bar_min_price=getattr(service_module, "GOLD_BAR_MIN_PRICE"),
        gold_bar_max_price=getattr(service_module, "GOLD_BAR_MAX_PRICE"),
    )
