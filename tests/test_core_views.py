from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from gameplay.constants import BUILDING_MAX_LEVELS
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
class TestCoreViews:
    """核心页面视图测试"""

    def test_home_page_anonymous(self, client):
        """匿名用户访问首页"""
        response = client.get(reverse("home"))
        assert response.status_code == 200

    def test_home_page_authenticated(self, authenticated_client):
        """登录用户访问首页"""
        ensure_manor(authenticated_client.user)
        response = authenticated_client.get(reverse("home"))
        assert response.status_code == 200
        assert "manor" in response.context

    def test_dashboard_requires_login(self, client):
        """仪表盘需要登录"""
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 302

    def test_dashboard_authenticated(self, manor_with_user):
        """登录用户访问仪表盘"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        assert "buildings" in response.context

    def test_dashboard_refresh_database_error_does_not_500(self, manor_with_user, monkeypatch):
        """数据库故障时仪表盘应降级而不是返回500。"""
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.views.core.sync_resource_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        assert "操作失败，请稍后重试" in response.content.decode("utf-8")

    def test_dashboard_refresh_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        """编程错误不应被页面层吞掉。"""
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.views.core.sync_resource_production",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.get(reverse("gameplay:dashboard"))

    def test_authenticated_layout_contains_partial_nav_markers(self, manor_with_user):
        """认证页面应包含局部导航刷新容器与脚本。"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'id="main-nav"' in body
        assert 'id="info-bar"' in body
        assert 'id="page-shell"' in body
        assert 'id="page-extra-scripts"' in body
        assert "js/nav_partial.js" in body
        assert body.count('data-partial-nav="1"') >= 12
        assert f'href="{reverse("gameplay:warehouse")}" data-partial-nav="1"' in body
        assert f'href="{reverse("trade:trade")}" data-partial-nav="1"' in body

    def test_dashboard_upgrading_building_has_auto_refresh_countdown(self, manor_with_user):
        """建筑升级倒计时应携带自动刷新标记。"""
        manor, client = manor_with_user
        building = manor.buildings.select_related("building_type").first()
        assert building is not None
        building.is_upgrading = True
        building.upgrade_complete_at = timezone.now() + timezone.timedelta(minutes=5)
        building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

        response = client.get(
            reverse(
                "gameplay:buildings_category",
                kwargs={"category": building.building_type.category},
            )
        )
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'data-countdown="' in body
        assert 'data-refresh="1"' in body

    def test_dashboard_max_level_building_shows_maxed_state(self, manor_with_user):
        """达到建筑等级上限时，页面应显示满级、禁用升级按钮，并将升级消耗显示为 /。"""
        manor, client = manor_with_user
        building = manor.buildings.select_related("building_type").get(building_type__key="juxianzhuang")
        max_level = BUILDING_MAX_LEVELS[building.building_type.key]
        building.level = max_level
        building.is_upgrading = False
        building.upgrade_complete_at = None
        building.save(update_fields=["level", "is_upgrading", "upgrade_complete_at"])

        response = client.get(
            reverse(
                "gameplay:buildings_category",
                kwargs={"category": building.building_type.category},
            )
        )
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert f"Lv {max_level} / {max_level} 满级" in body
        assert "<span>/</span>" in body
        assert "disabled>已满级</button>" in body

    def test_settings_page(self, manor_with_user):
        """设置页面"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:settings"))
        assert response.status_code == 200

    def test_rename_manor_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.rename_manor",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("rename blocked")),
        )

        response = client.post(reverse("gameplay:rename_manor"), {"new_name": "新庄园名"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:settings")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("rename blocked" in m for m in messages)

    def test_rename_manor_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.rename_manor",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:rename_manor"), {"new_name": "新庄园名"})
        assert response.status_code == 302
        assert response.url == reverse("gameplay:settings")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_rename_manor_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        monkeypatch.setattr(
            "gameplay.services.rename_manor",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(reverse("gameplay:rename_manor"), {"new_name": "新庄园名"})

    def test_ranking_page(self, manor_with_user):
        """排行榜页面"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:ranking"))
        assert response.status_code == 200
        assert "ranking" in response.context
