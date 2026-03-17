from __future__ import annotations

from typing import Any, Callable

from .cache_resilience import (
    best_effort_cache_add,
    best_effort_cache_delete,
    best_effort_cache_get,
    best_effort_cache_set,
    strict_cache_add,
    strict_cache_get,
)


def configure_rate_calculation_hooks(
    rate_calculations_module: Any,
    *,
    service_module: Any,
    imported_get_effective_gold_supply: Callable[..., Any],
    imported_calculate_supply_factor: Callable[..., Any],
) -> None:
    rate_calculations_module.configure_bank_service_hooks(
        safe_cache_get=lambda key, default=None: getattr(service_module, "_safe_cache_get")(key, default),  # type: ignore[misc]
        safe_cache_set=lambda key, value, timeout: getattr(service_module, "_safe_cache_set")(key, value, timeout),
        safe_cache_add=lambda key, value, timeout: getattr(service_module, "_safe_cache_add")(key, value, timeout),
        safe_cache_delete=lambda key: getattr(service_module, "_safe_cache_delete")(key),
        release_cache_lock_if_owner=lambda lock_key, lock_token: getattr(
            service_module, "_release_cache_lock_if_owner"
        )(lock_key, lock_token),
        get_today_exchange_count=lambda manor: getattr(service_module, "get_today_exchange_count")(manor),
        get_effective_gold_supply_override=lambda: (
            getattr(service_module, "get_effective_gold_supply")
            if getattr(service_module, "get_effective_gold_supply") is not imported_get_effective_gold_supply
            else None
        ),
        calculate_supply_factor_override=lambda: (
            getattr(service_module, "calculate_supply_factor")
            if getattr(service_module, "calculate_supply_factor") is not imported_calculate_supply_factor
            else None
        ),
    )


def get_today_exchange_count(
    manor: Any,
    *,
    aggregate_quantity: Callable[..., Any],
    now_func: Callable[[], Any],
    safe_int: Callable[..., int],
) -> int:
    today = now_func().date()
    count = aggregate_quantity(manor=manor, exchange_date=today)["total"]
    return max(0, safe_int(count, 0))


def safe_cache_get(
    key: str,
    default: Any = None,
    *,
    cache_backend: Any,
    logger: Any,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> Any:
    return best_effort_cache_get(
        cache_backend,
        key,
        default,
        logger=logger,
        component=component,
        infrastructure_exceptions=infrastructure_exceptions,
    )


def safe_cache_set(
    key: str,
    value: Any,
    timeout: int,
    *,
    cache_backend: Any,
    logger: Any,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> None:
    best_effort_cache_set(
        cache_backend,
        key,
        value,
        timeout,
        logger=logger,
        component=component,
        infrastructure_exceptions=infrastructure_exceptions,
    )


def safe_cache_add(
    key: str,
    value: Any,
    timeout: int,
    *,
    cache_backend: Any,
    logger: Any,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> bool:
    return best_effort_cache_add(
        cache_backend,
        key,
        value,
        timeout,
        logger=logger,
        component=component,
        infrastructure_exceptions=infrastructure_exceptions,
    )


def safe_cache_delete(
    key: str,
    *,
    cache_backend: Any,
    logger: Any,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
) -> None:
    best_effort_cache_delete(
        cache_backend,
        key,
        logger=logger,
        component=component,
        infrastructure_exceptions=infrastructure_exceptions,
    )


def strict_cache_get_entry(
    key: str,
    default: Any = None,
    *,
    cache_backend: Any,
    logger: Any,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
    unavailable_error_factory: Callable[[], Exception],
) -> Any:
    return strict_cache_get(
        cache_backend,
        key,
        default,
        logger=logger,
        component=component,
        infrastructure_exceptions=infrastructure_exceptions,
        unavailable_error_factory=unavailable_error_factory,
    )


def strict_cache_add_entry(
    key: str,
    value: Any,
    timeout: int,
    *,
    cache_backend: Any,
    logger: Any,
    component: str,
    infrastructure_exceptions: tuple[type[BaseException], ...],
    unavailable_error_factory: Callable[[], Exception],
) -> bool:
    return strict_cache_add(
        cache_backend,
        key,
        value,
        timeout,
        logger=logger,
        component=component,
        infrastructure_exceptions=infrastructure_exceptions,
        unavailable_error_factory=unavailable_error_factory,
    )


def release_cache_lock_if_owner_entry(
    lock_key: str,
    lock_token: str,
    *,
    release_cache_key_if_owner: Callable[..., bool],
    logger: Any,
    log_context: str,
    safe_cache_get: Callable[..., Any],
    safe_cache_delete: Callable[..., None],
) -> None:
    released = release_cache_key_if_owner(
        lock_key,
        lock_token=lock_token,
        logger=logger,
        log_context=log_context,
    )
    if released:
        return

    current_token = safe_cache_get(lock_key)
    if current_token == lock_token:
        safe_cache_delete(lock_key)


def grant_gold_bars_locked(
    manor: Any,
    quantity: int,
    *,
    add_item_to_inventory_locked: Callable[..., Any],
    gold_bar_item_key: str,
) -> None:
    try:
        add_item_to_inventory_locked(manor, gold_bar_item_key, quantity)
    except ValueError as exc:
        if str(exc) == f"物品模板不存在: {gold_bar_item_key}":
            raise ValueError("金条物品不存在，请联系管理员") from exc
        raise


def spend_exchange_cost_locked(
    manor: Any,
    quantity: int,
    cost_info: dict[str, Any],
    *,
    spend_resources_locked: Callable[..., Any],
    bank_exchange_reason: Any,
) -> int:
    total_cost = int(cost_info["total_cost"])
    try:
        spend_resources_locked(
            manor,
            {"silver": total_cost},
            note=f"兑换金条 x{quantity}",
            reason=bank_exchange_reason,
        )
    except ValueError as exc:
        raise ValueError(
            f"银两不足，需要 {total_cost:,} 银两" f"（基础 {cost_info['base_cost']:,} + 手续费 {cost_info['fee']:,}）"
        ) from exc
    return total_cost


def record_gold_bar_exchange_locked(
    manor: Any,
    quantity: int,
    total_cost: int,
    *,
    gold_bar_exchange_log_model: Any,
) -> None:
    gold_bar_exchange_log_model.objects.create(manor=manor, quantity=quantity, silver_cost=total_cost)


def build_exchange_result(
    manor: Any,
    quantity: int,
    cost_info: dict[str, Any],
    *,
    build_exchange_result_payload: Callable[..., dict[str, Any]],
    calculate_next_rate: Callable[..., int],
) -> dict[str, Any]:
    return build_exchange_result_payload(manor, quantity, cost_info, calculate_next_rate=calculate_next_rate)
