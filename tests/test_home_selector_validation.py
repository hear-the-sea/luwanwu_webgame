from __future__ import annotations

from types import SimpleNamespace

import pytest
from django_redis.exceptions import ConnectionInterrupted

import gameplay.services.raid as raid_service
from gameplay.selectors.home import _normalize_hourly_rates, get_home_context


def test_normalize_hourly_rates_coerces_invalid_values():
    normalized = _normalize_hourly_rates(
        {
            "grain": "120",
            "silver": "invalid",
            "stone": None,
            "wood": -8,
            "iron": 3.8,
            123: 456,
        }
    )

    assert normalized == {
        "grain": 120,
        "silver": 0,
        "stone": 0,
        "wood": 0,
        "iron": 3,
    }


def test_normalize_hourly_rates_rejects_non_mapping_input():
    assert _normalize_hourly_rates(None) == {}
    assert _normalize_hourly_rates("bad") == {}


class _FakeQuerySet(list):
    def all(self):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def select_related(self, *_args, **_kwargs):
        return self

    def prefetch_related(self, *_args, **_kwargs):
        return self


def test_get_home_context_tolerates_cache_backend_failure(monkeypatch):
    monkeypatch.setattr("gameplay.selectors.home.optimize_guest_queryset", lambda qs: qs)
    monkeypatch.setattr("gameplay.selectors.home.get_technology_template", lambda *_a, **_k: {})
    monkeypatch.setattr("gameplay.selectors.home.can_retreat", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "gameplay.selectors.home.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.home.cache.set",
        lambda *_a, **_k: (_ for _ in ()).throw(ConnectionInterrupted("cache down")),
    )
    monkeypatch.setattr(
        "gameplay.utils.resource_calculator.get_hourly_rates", lambda *_a, **_k: {"grain": "12", "silver": 8}
    )
    monkeypatch.setattr("gameplay.utils.resource_calculator.get_personnel_grain_cost_per_hour", lambda *_a, **_k: 3)
    monkeypatch.setattr(raid_service, "get_active_scouts", lambda *_a, **_k: [])
    monkeypatch.setattr(raid_service, "get_active_raids", lambda *_a, **_k: [])
    monkeypatch.setattr(raid_service, "get_incoming_raids", lambda *_a, **_k: [])

    manor = SimpleNamespace(
        pk=1,
        grain=100,
        silver=200,
        retainer_count=3,
        retainer_capacity=10,
        guests=_FakeQuerySet(),
        mission_runs=_FakeQuerySet(),
        buildings=_FakeQuerySet(),
        technologies=_FakeQuerySet(),
        troops=_FakeQuerySet(),
    )

    context = get_home_context(manor)

    assert context["grain_production"] == 12
    assert context["personnel_grain_cost"] == 3
    assert context["building_income"] == [
        {"resource": "grain", "label": "粮食", "rate": 12},
        {"resource": "silver", "label": "银两", "rate": 8},
    ]


def test_get_home_context_runtime_marker_cache_error_bubbles_up(monkeypatch):
    monkeypatch.setattr("gameplay.selectors.home.optimize_guest_queryset", lambda qs: qs)
    monkeypatch.setattr("gameplay.selectors.home.get_technology_template", lambda *_a, **_k: {})
    monkeypatch.setattr("gameplay.selectors.home.can_retreat", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "gameplay.selectors.home.cache.get",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )
    monkeypatch.setattr(
        "gameplay.utils.resource_calculator.get_hourly_rates", lambda *_a, **_k: {"grain": "12", "silver": 8}
    )
    monkeypatch.setattr("gameplay.utils.resource_calculator.get_personnel_grain_cost_per_hour", lambda *_a, **_k: 3)
    monkeypatch.setattr(raid_service, "get_active_scouts", lambda *_a, **_k: [])
    monkeypatch.setattr(raid_service, "get_active_raids", lambda *_a, **_k: [])
    monkeypatch.setattr(raid_service, "get_incoming_raids", lambda *_a, **_k: [])

    manor = SimpleNamespace(
        pk=1,
        grain=100,
        silver=200,
        retainer_count=3,
        retainer_capacity=10,
        guests=_FakeQuerySet(),
        mission_runs=_FakeQuerySet(),
        buildings=_FakeQuerySet(),
        technologies=_FakeQuerySet(),
        troops=_FakeQuerySet(),
    )

    with pytest.raises(RuntimeError, match="cache down"):
        get_home_context(manor)
