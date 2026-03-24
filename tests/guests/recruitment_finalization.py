from __future__ import annotations

import pytest
from django.utils import timezone

from core.exceptions import MessageError, NoTemplateAvailableError
from guests.models import GuestRecruitment, RecruitmentPool
from guests.services.recruitment import finalize_guest_recruitment, start_guest_recruitment
from tests.guests.support import create_manor


def _start_due_recruitment(manor, *, seed: int):
    recruitment = start_guest_recruitment(manor, RecruitmentPool.objects.get(key="cunmu"), seed=seed)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])
    return recruitment


@pytest.mark.django_db
def test_finalize_guest_recruitment_generates_candidates(game_data, django_user_model, load_guest_data):
    manor = create_manor(django_user_model, username="player_recruit_async_finalize", silver=50000)
    recruitment = _start_due_recruitment(manor, seed=42)

    assert finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=False) is True

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_keeps_success_when_notification_fails(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(django_user_model, username="player_recruit_async_notify_fail", silver=50000)
    recruitment = _start_due_recruitment(manor, seed=99)

    monkeypatch.setattr(
        "guests.services.recruitment_followups.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )
    monkeypatch.setattr(
        "guests.services.recruitment_followups.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=True) is True

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_runtime_marker_notification_error_bubbles_up(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(
        django_user_model,
        username="player_recruit_async_notify_runtime_backend",
        silver=50000,
    )
    recruitment = _start_due_recruitment(manor, seed=109)

    monkeypatch.setattr(
        "guests.services.recruitment_followups.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_notification_programming_error_bubbles_up(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(
        django_user_model,
        username="player_recruit_async_notify_program_error",
        silver=50000,
    )
    recruitment = _start_due_recruitment(manor, seed=199)

    monkeypatch.setattr(
        "guests.services.recruitment_followups.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken message contract")),
    )

    with pytest.raises(AssertionError, match="broken message contract"):
        finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_marks_failed_for_known_recruitment_error(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(django_user_model, username="player_recruit_async_known_error", silver=50000)
    recruitment = _start_due_recruitment(manor, seed=808)

    monkeypatch.setattr(
        "guests.services.recruitment._build_recruitment_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(NoTemplateAvailableError()),
    )

    assert finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=False) is False

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.FAILED
    assert "缺少可用的门客模板" in recruitment.error_message


@pytest.mark.django_db
def test_finalize_guest_recruitment_does_not_mask_contract_error(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(django_user_model, username="player_recruit_async_contract_error", silver=50000)
    recruitment = _start_due_recruitment(manor, seed=909)

    monkeypatch.setattr(
        "guests.services.recruitment._build_recruitment_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid recruitment contract")),
    )

    with pytest.raises(AssertionError, match="invalid recruitment contract"):
        finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=False)

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.PENDING
    assert recruitment.error_message == ""
