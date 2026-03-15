"""
打工系统视图测试
"""

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from gameplay.models import WorkAssignment, WorkTemplate
from guests.models import Guest, GuestArchetype, GuestRarity, GuestStatus, GuestTemplate


@pytest.mark.django_db
class TestWorkViews:
    """打工系统视图测试"""

    @staticmethod
    def _create_work_data(
        manor,
        suffix: str,
        *,
        tier: str = WorkTemplate.Tier.JUNIOR,
        display_order: int = 0,
    ) -> tuple[Guest, WorkTemplate]:
        guest_template = GuestTemplate.objects.create(
            key=f"view_work_guest_tpl_{suffix}_{manor.id}",
            name=f"打工门客模板{suffix}",
            archetype=GuestArchetype.CIVIL,
            rarity=GuestRarity.GRAY,
        )
        guest = Guest.objects.create(
            manor=manor,
            template=guest_template,
            status=GuestStatus.IDLE,
        )
        work_template = WorkTemplate.objects.create(
            key=f"view_work_template_{suffix}_{manor.id}",
            name=f"打工模板{suffix}",
            tier=tier,
            required_level=1,
            required_force=0,
            required_intellect=0,
            reward_silver=100,
            work_duration=3600,
            display_order=display_order,
        )
        return guest, work_template

    def test_work_page(self, manor_with_user):
        """打工页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:work"))
        assert response.status_code == 200
        assert "works" in response.context

    def test_work_page_shows_assignment_in_matching_work_card(self, manor_with_user):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "inline_assignment")
        WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.WORKING,
            complete_at=timezone.now() + timezone.timedelta(minutes=30),
        )

        response = client.get(reverse("gameplay:work"))
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "执行门客" in body
        assert guest.display_name in body
        assert "打工中 (" not in body

    def test_work_tier_filter(self, manor_with_user):
        """打工等级过滤"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:work") + "?tier=senior")
        assert response.status_code == 200
        assert response.context["current_tier"] == "senior"

    def test_work_page_paginates_four_works_per_tier(self, manor_with_user):
        manor, client = manor_with_user
        for index in range(5):
            self._create_work_data(
                manor,
                f"page_{index}",
                tier=WorkTemplate.Tier.SENIOR,
                display_order=index + 1,
            )

        response = client.get(reverse("gameplay:work") + "?tier=senior")
        assert response.status_code == 200
        assert len(response.context["works"]) == 4
        assert response.context["page_obj"].number == 1
        assert response.context["is_paginated"] is True
        body = response.content.decode("utf-8")
        assert "打工模板page_0" in body
        assert "打工模板page_3" in body
        assert "打工模板page_4" not in body
        assert "?tier=senior&page=2" in body

        second_page = client.get(reverse("gameplay:work") + "?tier=senior&page=2")
        assert second_page.status_code == 200
        assert len(second_page.context["works"]) == 1
        assert second_page.context["page_obj"].number == 2
        second_body = second_page.content.decode("utf-8")
        assert "打工模板page_4" in second_body
        assert "打工模板page_0" not in second_body

    def test_assign_work_redirects_back_to_current_page_when_next_provided(self, manor_with_user):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "assign_next", tier=WorkTemplate.Tier.SENIOR)
        next_url = reverse("gameplay:work") + "?tier=senior&page=2"

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": guest.id, "work_key": work_template.key, "next": next_url},
        )

        assert response.status_code == 302
        assert response.url == next_url

    def test_recall_work_redirects_back_to_current_page_when_next_provided(self, manor_with_user):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "recall_next", tier=WorkTemplate.Tier.SENIOR)
        assignment = WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.WORKING,
            complete_at=timezone.now() + timezone.timedelta(minutes=30),
        )
        next_url = reverse("gameplay:work") + "?tier=senior&page=2"

        response = client.post(
            reverse("gameplay:recall_work", kwargs={"pk": assignment.pk}),
            {"next": next_url},
        )

        assert response.status_code == 302
        assert response.url == next_url

    def test_claim_work_reward_redirects_back_to_current_page_when_next_provided(self, manor_with_user):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "claim_next", tier=WorkTemplate.Tier.SENIOR)
        assignment = WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.COMPLETED,
            complete_at=timezone.now(),
        )
        next_url = reverse("gameplay:work") + "?tier=senior&page=2"

        response = client.post(
            reverse("gameplay:claim_work_reward", kwargs={"pk": assignment.pk}),
            {"next": next_url},
        )

        assert response.status_code == 302
        assert response.url == next_url

    def test_assign_work_known_error_shows_message(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "assign_known")

        monkeypatch.setattr(
            "gameplay.views.work.assign_guest_to_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("work blocked")),
        )

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": guest.id, "work_key": work_template.key},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("work blocked" in m for m in messages)

    def test_assign_work_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "assign_exc")

        monkeypatch.setattr(
            "gameplay.views.work.assign_guest_to_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": guest.id, "work_key": work_template.key},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_assign_work_programming_error_bubbles_up(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "assign_runtime")

        monkeypatch.setattr(
            "gameplay.views.work.assign_guest_to_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                reverse("gameplay:assign_work"),
                {"guest_id": guest.id, "work_key": work_template.key},
            )

    def test_assign_work_rejects_invalid_guest_id(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        _guest, work_template = self._create_work_data(manor, "invalid_guest_id")
        called = {"count": 0}

        def _unexpected_assign(*_args, **_kwargs):
            called["count"] += 1

        monkeypatch.setattr("gameplay.views.work.assign_guest_to_work", _unexpected_assign)

        response = client.post(
            reverse("gameplay:assign_work"),
            {"guest_id": "abc", "work_key": work_template.key},
        )
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("参数错误" in m for m in messages)
        assert called["count"] == 0

    def test_recall_work_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "recall_exc")
        assignment = WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.WORKING,
            complete_at=timezone.now(),
        )

        monkeypatch.setattr(
            "gameplay.views.work.recall_guest_from_work",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:recall_work", kwargs={"pk": assignment.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)

    def test_claim_work_reward_database_error_does_not_500(self, manor_with_user, monkeypatch):
        manor, client = manor_with_user
        guest, work_template = self._create_work_data(manor, "claim_exc")
        assignment = WorkAssignment.objects.create(
            manor=manor,
            guest=guest,
            work_template=work_template,
            status=WorkAssignment.Status.COMPLETED,
            complete_at=timezone.now(),
        )

        monkeypatch.setattr(
            "gameplay.views.work.claim_work_reward",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
        )

        response = client.post(reverse("gameplay:claim_work_reward", kwargs={"pk": assignment.pk}))
        assert response.status_code == 302
        assert response.url == reverse("gameplay:work")
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("操作失败，请稍后重试" in m for m in messages)
