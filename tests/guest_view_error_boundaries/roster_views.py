from __future__ import annotations

import pytest
from django.db import DatabaseError
from django.urls import reverse

from tests.guest_view_error_boundaries.support import create_guest, login_client, messages


@pytest.mark.django_db
def test_dismiss_guest_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="dismiss_db")
    guest = create_guest(manor, prefix="dismiss_db")

    monkeypatch.setattr(
        "guests.views.roster.dismiss_guest", lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down"))
    )

    response = client.post(reverse("guests:dismiss", args=[guest.pk]))

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "辞退失败：操作失败，请稍后重试" in messages(response)


@pytest.mark.django_db
def test_dismiss_guest_view_runtime_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="dismiss_runtime")
    guest = create_guest(manor, prefix="dismiss_runtime")

    monkeypatch.setattr(
        "guests.views.roster.dismiss_guest", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("guests:dismiss", args=[guest.pk]))


@pytest.mark.django_db
def test_dismiss_guest_view_legacy_value_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="dismiss_value_error")
    guest = create_guest(manor, prefix="dismiss_value_error")

    monkeypatch.setattr(
        "guests.views.roster.dismiss_guest", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("legacy dismiss"))
    )

    with pytest.raises(ValueError, match="legacy dismiss"):
        client.post(reverse("guests:dismiss", args=[guest.pk]))
