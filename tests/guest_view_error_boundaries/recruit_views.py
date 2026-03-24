from __future__ import annotations

import pytest
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import GameError
from tests.guest_view_error_boundaries.support import (
    ajax_headers,
    create_candidate,
    create_pool,
    login_client,
    messages,
    stub_recruit_lock,
)


@pytest.mark.django_db
def test_recruit_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, _manor = login_client(django_user_model, prefix="recruit_db")
    pool = create_pool("recruit_db")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.start_guest_recruitment",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in messages(response)


@pytest.mark.django_db
def test_recruit_view_runtime_error_bubbles_up(django_user_model, monkeypatch):
    client, _manor = login_client(django_user_model, prefix="recruit_runtime")
    pool = create_pool("recruit_runtime")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.start_guest_recruitment",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})


@pytest.mark.django_db
def test_recruit_view_legacy_value_error_bubbles_up(django_user_model, monkeypatch):
    client, _manor = login_client(django_user_model, prefix="recruit_value_error")
    pool = create_pool("recruit_value_error")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.start_guest_recruitment",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("legacy business error")),
    )

    with pytest.raises(ValueError, match="legacy business error"):
        client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})


@pytest.mark.django_db
def test_accept_candidate_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="accept_db")
    candidate = create_candidate(manor, prefix="accept_db")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.bulk_finalize_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:candidate_accept"),
        {"candidate_ids": [str(candidate.pk)], "action": "accept"},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in messages(response)


@pytest.mark.django_db
def test_accept_candidate_view_runtime_error_bubbles_up(django_user_model, monkeypatch):
    client, manor = login_client(django_user_model, prefix="accept_runtime")
    candidate = create_candidate(manor, prefix="accept_runtime")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.bulk_finalize_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            reverse("guests:candidate_accept"),
            {"candidate_ids": [str(candidate.pk)], "action": "accept"},
        )


@pytest.mark.django_db
def test_use_magnifying_glass_view_game_error_returns_business_json(django_user_model, monkeypatch):
    client, _manor = login_client(django_user_model, prefix="magnify_game")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(GameError("放大镜失效")),
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        **ajax_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "放大镜失效"


@pytest.mark.django_db
def test_use_magnifying_glass_view_database_error_returns_generic_json(django_user_model, monkeypatch):
    client, _manor = login_client(django_user_model, prefix="magnify_db")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        **ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_use_magnifying_glass_view_runtime_error_bubbles_up(django_user_model, monkeypatch):
    client, _manor = login_client(django_user_model, prefix="magnify_runtime")
    stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            reverse("guests:use_magnifying_glass"),
            {"item_id": "1"},
            **ajax_headers(),
        )
