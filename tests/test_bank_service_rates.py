"""Tests for bank service dynamic rate calculations."""

from __future__ import annotations

from types import SimpleNamespace

from trade.services import bank_service


def test_calculate_supply_factor_returns_min_when_no_supply(monkeypatch):
    """Test that supply factor returns minimum when supply is zero."""
    monkeypatch.setattr(bank_service, "get_effective_gold_supply", lambda: 0)

    factor = bank_service.calculate_supply_factor()

    assert factor == 0.85  # Minimum factor


def test_calculate_supply_factor_returns_one_at_target(monkeypatch):
    """Test that supply factor is approximately 1.0 at target supply."""
    monkeypatch.setattr(bank_service, "get_effective_gold_supply", lambda: bank_service.GOLD_BAR_TARGET_SUPPLY)

    factor = bank_service.calculate_supply_factor()

    # At target supply, log2(1) = 0, so factor = 1 + 0 = 1.0
    assert abs(factor - 1.0) < 0.01


def test_calculate_supply_factor_increases_with_more_supply(monkeypatch):
    """Test that supply factor increases when supply exceeds target."""
    monkeypatch.setattr(bank_service, "get_effective_gold_supply", lambda: bank_service.GOLD_BAR_TARGET_SUPPLY * 2)

    factor = bank_service.calculate_supply_factor()

    # Double supply means log2(2) = 1, so factor = 1 + 0.12 = 1.12
    assert factor > 1.0
    assert factor <= 1.40  # Max cap


def test_calculate_supply_factor_capped_at_max(monkeypatch):
    """Test that supply factor is capped at maximum."""
    # Very high supply
    monkeypatch.setattr(bank_service, "get_effective_gold_supply", lambda: bank_service.GOLD_BAR_TARGET_SUPPLY * 100)

    factor = bank_service.calculate_supply_factor()

    assert factor == 1.40  # Max cap


def test_calculate_progressive_factor_starts_at_one():
    """Test that progressive factor starts at 1.0 for first purchase."""
    factor = bank_service.calculate_progressive_factor(0)

    assert factor == 1.0


def test_calculate_progressive_factor_increases_linearly():
    """Test that progressive factor increases with each purchase."""
    factor_1 = bank_service.calculate_progressive_factor(1)
    factor_5 = bank_service.calculate_progressive_factor(5)
    factor_10 = bank_service.calculate_progressive_factor(10)

    assert factor_1 == 1.05  # 1 + 0.05 * 1
    assert factor_5 == 1.25  # 1 + 0.05 * 5
    assert factor_10 == 1.50  # 1 + 0.05 * 10


def test_calculate_progressive_factor_capped_at_max():
    """Test that progressive factor is capped at maximum."""
    factor = bank_service.calculate_progressive_factor(20)

    assert factor == 1.60  # Max cap


def test_calculate_dynamic_rate_respects_min_price(monkeypatch):
    """Test that dynamic rate doesn't go below minimum."""
    monkeypatch.setattr(bank_service, "calculate_supply_factor", lambda: 0.5)  # Very low
    monkeypatch.setattr(bank_service, "get_today_exchange_count", lambda _manor: 0)

    manor = SimpleNamespace(pk=1)
    rate = bank_service.calculate_dynamic_rate(manor)

    assert rate >= bank_service.GOLD_BAR_MIN_PRICE


def test_calculate_dynamic_rate_respects_max_price(monkeypatch):
    """Test that dynamic rate doesn't exceed maximum."""
    monkeypatch.setattr(bank_service, "calculate_supply_factor", lambda: 2.0)  # Very high
    monkeypatch.setattr(bank_service, "get_today_exchange_count", lambda _manor: 20)

    manor = SimpleNamespace(pk=1)
    rate = bank_service.calculate_dynamic_rate(manor)

    assert rate <= bank_service.GOLD_BAR_MAX_PRICE


def test_calculate_gold_bar_cost_accumulates_progressive_rates(monkeypatch):
    """Test that cost calculation accumulates different rates per bar."""
    monkeypatch.setattr(bank_service, "calculate_supply_factor", lambda: 1.0)
    monkeypatch.setattr(bank_service, "get_today_exchange_count", lambda _manor: 0)

    manor = SimpleNamespace(pk=1)
    cost_info = bank_service.calculate_gold_bar_cost(manor, 3)

    # Each bar should have a different rate
    assert len(cost_info["rate_details"]) == 3
    # Rates should increase progressively
    assert cost_info["rate_details"][0] < cost_info["rate_details"][1] < cost_info["rate_details"][2]
    # Total should be sum of individual rates plus fee
    expected_base = sum(cost_info["rate_details"])
    assert cost_info["base_cost"] == expected_base
    assert cost_info["fee"] == int(expected_base * bank_service.GOLD_BAR_FEE_RATE)
    assert cost_info["total_cost"] == expected_base + cost_info["fee"]


def test_calculate_next_rate_is_higher_than_current(monkeypatch):
    """Test that next rate is higher than current rate."""
    monkeypatch.setattr(bank_service, "calculate_supply_factor", lambda: 1.0)
    monkeypatch.setattr(bank_service, "get_today_exchange_count", lambda _manor: 5)

    manor = SimpleNamespace(pk=1)
    current = bank_service.calculate_dynamic_rate(manor)
    next_rate = bank_service.calculate_next_rate(manor)

    assert next_rate > current
