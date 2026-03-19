from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse

from guests.models import Guest, GuestArchetype, GuestRarity, GuestStatus, GuestTemplate


def _create_guest(manor, *, key_suffix: str) -> Guest:
    template = GuestTemplate.objects.create(
        key=f"salary_view_guest_tpl_{key_suffix}_{manor.id}",
        name=f"工资视图门客模板{key_suffix}",
        archetype=GuestArchetype.CIVIL,
        rarity=GuestRarity.GRAY,
    )
    return Guest.objects.create(
        manor=manor,
        template=template,
        status=GuestStatus.IDLE,
    )


@pytest.mark.django_db
def test_pay_salary_view_database_error_degrades_with_message(manor_with_user, monkeypatch):
    manor, client = manor_with_user
    guest = _create_guest(manor, key_suffix="db")

    monkeypatch.setattr(
        "guests.services.salary.pay_guest_salary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:pay_salary", kwargs={"pk": guest.pk}))

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_pay_salary_view_get_manor_database_error_degrades_with_message(manor_with_user, monkeypatch):
    _manor, client = manor_with_user

    monkeypatch.setattr(
        "gameplay.services.manor.core.get_manor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:pay_salary", kwargs={"pk": 999999}))

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_pay_salary_view_guest_lookup_database_error_degrades_with_message(manor_with_user, monkeypatch):
    manor, client = manor_with_user
    guest = _create_guest(manor, key_suffix="lookup-db")

    monkeypatch.setattr(
        "guests.views.salary.get_object_or_404",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:pay_salary", kwargs={"pk": guest.pk}))

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_pay_salary_view_programming_error_bubbles_up(manor_with_user, monkeypatch):
    manor, client = manor_with_user
    guest = _create_guest(manor, key_suffix="runtime")

    monkeypatch.setattr(
        "guests.services.salary.pay_guest_salary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("guests:pay_salary", kwargs={"pk": guest.pk}))


@pytest.mark.django_db
def test_pay_all_salaries_view_database_error_degrades_with_message(manor_with_user, monkeypatch):
    _manor, client = manor_with_user

    monkeypatch.setattr(
        "guests.services.salary.pay_all_salaries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:pay_all_salaries"))

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_pay_all_salaries_view_get_manor_database_error_degrades_with_message(manor_with_user, monkeypatch):
    _manor, client = manor_with_user

    monkeypatch.setattr(
        "gameplay.services.manor.core.get_manor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:pay_all_salaries"))

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_pay_all_salaries_view_programming_error_bubbles_up(manor_with_user, monkeypatch):
    _manor, client = manor_with_user

    monkeypatch.setattr(
        "guests.services.salary.pay_all_salaries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("guests:pay_all_salaries"))
