from __future__ import annotations

import pytest
from django.db import DatabaseError
from django.urls import reverse

from gameplay.models import Manor
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
def test_trade_view_renders(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.build_trade_page_context", lambda *_args, **_kwargs: {"current_tab": "shop"})

    user = django_user_model.objects.create_user(username="trade_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_trade_view_creates_manor_when_missing(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.build_trade_page_context", lambda *_args, **_kwargs: {"current_tab": "shop"})

    user = django_user_model.objects.create_user(username="trade_view_create_manor", password="pass12345")
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200
    assert Manor.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_trade_view_tolerates_resource_sync_error(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.page_context.get_trade_context", lambda *_args, **_kwargs: {"current_tab": "shop"})
    monkeypatch.setattr(
        "trade.page_context.project_resource_production_for_read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("sync failed")),
    )

    user = django_user_model.objects.create_user(username="trade_view_sync_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_trade_view_renders_bank_degraded_banner_and_disables_exchange(monkeypatch, client, django_user_model):
    user = django_user_model.objects.create_user(username="trade_view_bank_degraded", password="pass12345")
    manor = ensure_manor(user)
    monkeypatch.setattr(
        "trade.views.build_trade_page_context",
        lambda *_args, **_kwargs: {
            "current_tab": "bank",
            "tabs": [{"key": "bank", "name": "钱庄"}],
            "manor": manor,
            "trade_alerts": [{"section": "bank", "message": "钱庄汇率数据暂时不可用，已暂时关闭兑换。"}],
            "bank_info": {
                "current_rate": 0,
                "next_rate": 0,
                "total_cost_per_bar": 0,
                "gold_bar_fee_rate": 0,
                "today_count": 0,
                "manor_silver": manor.silver,
                "effective_supply": 0,
                "supply_factor": 0,
                "progressive_factor": 0,
                "gold_bar_base_price": 0,
                "gold_bar_min_price": 0,
                "gold_bar_max_price": 0,
                "exchange_available": False,
            },
            "troop_bank_capacity": 5000,
            "troop_bank_used": 0,
            "troop_bank_remaining": 5000,
            "troop_bank_rows": [],
            "troop_bank_categories": [{"key": "all", "name": "全部"}],
            "troop_bank_current_category": "all",
        },
    )
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "钱庄汇率数据暂时不可用，已暂时关闭兑换。" in content
    assert "兑换暂不可用" in content
