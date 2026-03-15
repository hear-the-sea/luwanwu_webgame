from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse


@pytest.mark.django_db
class TestTechnologyViews:
    """科技系统视图测试"""

    def test_technology_page(self, manor_with_user):
        """科技页面"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology"))
        assert response.status_code == 200
        assert "technologies" in response.context
        content = response.content.decode("utf-8")
        assert 'class="tw-building-headline"' in content
        assert "Lv 0 /" in content

    def test_technology_martial_tab(self, manor_with_user):
        """武艺科技标签页"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology") + "?tab=martial")
        assert response.status_code == 200
        assert response.context["current_tab"] == "martial"

    def test_technology_invalid_tab_falls_back_to_basic(self, manor_with_user):
        """非法科技标签页应回退到基础分类。"""
        _manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology") + "?tab=unknown")
        assert response.status_code == 200
        assert response.context["current_tab"] == "basic"

    def test_upgrade_technology_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("tech blocked")),
        )

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "basic"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:technology')}?tab=basic"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("tech blocked" in m for m in messages)

    def test_upgrade_technology_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "basic"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:technology')}?tab=basic"
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_upgrade_technology_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
                {"tab": "basic"},
            )

    def test_upgrade_technology_redirects_to_safe_next_url(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: {"message": "ok"},
        )
        next_url = f"{reverse('gameplay:technology')}?tab=martial&troop=dao#tech-dao_attack"

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "basic", "next": next_url},
        )
        assert response.status_code == 302
        assert response.url == next_url

    def test_upgrade_technology_rejects_unsafe_next_url(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.views.technology.upgrade_technology",
            lambda *_args, **_kwargs: {"message": "ok"},
        )

        response = client.post(
            reverse("gameplay:upgrade_technology", kwargs={"tech_key": "dao_attack"}),
            {"tab": "martial", "troop": "dao", "next": "https://evil.example/phish"},
        )
        assert response.status_code == 302
        assert response.url == f"{reverse('gameplay:technology')}?tab=martial&troop=dao"
