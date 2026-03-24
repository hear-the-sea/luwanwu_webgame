from __future__ import annotations

import pytest
from django.db import DatabaseError
from django.urls import reverse

from guests.models import GuestSkill, Skill
from tests.guest_view_error_boundaries.support import create_guest, create_skill_book, login_client, messages, unique


@pytest.mark.django_db
def test_learn_skill_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="learn_db")
    guest = create_guest(manor, prefix="learn_db")
    _skill, item = create_skill_book(manor, prefix="learn_db")

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_learning",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:learn_skill", args=[guest.pk]), {"item_id": str(item.pk)})

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "操作失败，请稍后重试" in messages(response)


@pytest.mark.django_db
def test_learn_skill_view_runtime_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="learn_runtime")
    guest = create_guest(manor, prefix="learn_runtime")
    _skill, item = create_skill_book(manor, prefix="learn_runtime")

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_learning",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("guests:learn_skill", args=[guest.pk]), {"item_id": str(item.pk)})


@pytest.mark.django_db
def test_learn_skill_view_legacy_value_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="learn_value_error")
    guest = create_guest(manor, prefix="learn_value_error")
    _skill, item = create_skill_book(manor, prefix="learn_value_error")

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_learning",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("legacy learn")),
    )

    with pytest.raises(ValueError, match="legacy learn"):
        client.post(reverse("guests:learn_skill", args=[guest.pk]), {"item_id": str(item.pk)})


@pytest.mark.django_db
def test_forget_skill_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="forget_db")
    guest = create_guest(manor, prefix="forget_db")
    skill = Skill.objects.create(key=unique("forget_db_skill"), name="遗忘技能", rarity="green")
    guest_skill = GuestSkill.objects.create(guest=guest, skill=skill)

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_forget",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:forget_skill", args=[guest.pk]), {"guest_skill_id": str(guest_skill.pk)})

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "操作失败，请稍后重试" in messages(response)


@pytest.mark.django_db
def test_forget_skill_view_runtime_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="forget_runtime")
    guest = create_guest(manor, prefix="forget_runtime")
    skill = Skill.objects.create(key=unique("forget_runtime_skill"), name="遗忘技能", rarity="green")
    guest_skill = GuestSkill.objects.create(guest=guest, skill=skill)

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_forget",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("guests:forget_skill", args=[guest.pk]), {"guest_skill_id": str(guest_skill.pk)})


@pytest.mark.django_db
def test_forget_skill_view_legacy_value_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="forget_value_error")
    guest = create_guest(manor, prefix="forget_value_error")
    skill = Skill.objects.create(key=unique("forget_value_error_skill"), name="遗忘技能", rarity="green")
    guest_skill = GuestSkill.objects.create(guest=guest, skill=skill)

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_forget",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("legacy forget")),
    )

    with pytest.raises(ValueError, match="legacy forget"):
        client.post(reverse("guests:forget_skill", args=[guest.pk]), {"guest_skill_id": str(guest_skill.pk)})
