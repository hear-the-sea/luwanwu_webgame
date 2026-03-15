"""
募兵系统视图测试
"""

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse


@pytest.mark.django_db
class TestRecruitmentViews:
    """募兵系统视图测试"""

    def test_troop_recruitment_page(self, manor_with_user):
        """募兵页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:troop_recruitment"))
        assert response.status_code == 200
        assert "recruitment_options" in response.context

    def test_troop_recruitment_page_category_filter(self, manor_with_user):
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:troop_recruitment") + "?category=jian")
        assert response.status_code == 200
        assert response.context["current_category"] == "jian"
        assert "recruitment_categories" in response.context
        options = response.context["recruitment_options"]
        assert options
        assert all(option.get("troop_class") == "jian" for option in options)

    def test_start_troop_recruitment_database_error_does_not_500(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.recruitment.recruitment.start_troop_recruitment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:start_troop_recruitment"),
            {"troop_key": "any", "quantity": "1"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:troop_recruitment")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_start_troop_recruitment_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.recruitment.recruitment.start_troop_recruitment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:start_troop_recruitment"),
                {"troop_key": "any", "quantity": "1"},
            )

    def test_start_troop_recruitment_rejects_invalid_quantity(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user
        called = {"count": 0}

        def _unexpected_start(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.services.recruitment.recruitment.start_troop_recruitment", _unexpected_start)

        response = client.post(
            reverse("gameplay:start_troop_recruitment"),
            {"troop_key": "any", "quantity": "bad"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:troop_recruitment")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("无效的数量" in m for m in messages)
        assert called["count"] == 0

    def test_start_troop_recruitment_known_error_shows_message(self, manor_with_user, monkeypatch):
        _manor, client = manor_with_user

        monkeypatch.setattr(
            "gameplay.services.recruitment.recruitment.start_troop_recruitment",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("recruit blocked")),
        )

        response = client.post(
            reverse("gameplay:start_troop_recruitment"),
            {"troop_key": "any", "quantity": "1"},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:troop_recruitment")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("recruit blocked" in m for m in messages)
