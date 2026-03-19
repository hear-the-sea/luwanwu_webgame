"""
生产系统视图测试
"""

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from gameplay.models import HorseProduction, LivestockProduction, SmeltingProduction


@pytest.mark.django_db
class TestProductionViews:
    """生产系统视图测试"""

    def test_stable_page(self, manor_with_user):
        """马房页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:stable"))
        assert response.status_code == 200
        assert "horse_options" in response.context

    def test_stable_page_tolerates_resource_sync_error(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.views.production_page_context.project_resource_production_for_read",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("sync failed")),
        )

        response = client.get(reverse("gameplay:stable"))
        assert response.status_code == 200
        assert "horse_options" in response.context

    def test_stable_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        HorseProduction.objects.create(
            manor=manor,
            horse_key="test_horse",
            horse_name="测试马",
            quantity=1,
            grain_cost=10,
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=HorseProduction.Status.PRODUCING,
        )

        response = client.get(reverse("gameplay:stable"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_ranch_page(self, manor_with_user):
        """畜牧场页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:ranch"))
        assert response.status_code == 200
        assert "livestock_options" in response.context

    def test_ranch_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        LivestockProduction.objects.create(
            manor=manor,
            livestock_key="test_livestock",
            livestock_name="测试家畜",
            quantity=1,
            grain_cost=8,
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=LivestockProduction.Status.PRODUCING,
        )

        response = client.get(reverse("gameplay:ranch"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_smithy_page(self, manor_with_user):
        """冶炼坊页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:smithy"))
        assert response.status_code == 200
        assert "metal_options" in response.context

    def test_smithy_page_active_production_has_refresh_countdown(self, manor_with_user):
        manor, client = manor_with_user
        SmeltingProduction.objects.create(
            manor=manor,
            metal_key="test_metal",
            metal_name="测试物品",
            quantity=1,
            cost_type="silver",
            cost_amount=10,
            base_duration=60,
            actual_duration=60,
            complete_at=timezone.now() + timezone.timedelta(minutes=1),
            status=SmeltingProduction.Status.PRODUCING,
        )

        response = client.get(reverse("gameplay:smithy"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "js/dashboard.js" in body
        assert 'data-refresh="1"' in body

    def test_start_horse_production_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.production.start_horse_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:start_horse_production"), {"horse_key": "any", "quantity": "1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:stable")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_horse_production_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.production.start_horse_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:start_horse_production"), {"horse_key": "any", "quantity": "1"})

    def test_start_horse_production_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.production.start_horse_production", _unexpected_start)

        response = client.post(reverse("gameplay:start_horse_production"), {"horse_key": "any", "quantity": "-1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:stable")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_horse_production_rejects_missing_horse_key(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.production.start_horse_production", _unexpected_start)

        response = client.post(reverse("gameplay:start_horse_production"), {"quantity": "1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:stable")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("请选择马匹类型" in m for m in messages)
        assert called["count"] == 0

    def test_start_livestock_production_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.ranch.start_livestock_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:start_livestock_production"), {"livestock_key": "any", "quantity": "1"}
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:ranch")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_livestock_production_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.ranch.start_livestock_production", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_livestock_production"),
            {"livestock_key": "any", "quantity": "bad"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:ranch")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_smelting_production_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.buildings.smithy.start_smelting_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:start_smelting_production"), {"metal_key": "any", "quantity": "1"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:smithy")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_smelting_production_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.buildings.smithy.start_smelting_production", _unexpected_start)

        response = client.post(reverse("gameplay:start_smelting_production"), {"metal_key": "any", "quantity": "0"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:smithy")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0
