from __future__ import annotations

import pytest

from battle.models import TroopTemplate
from core.exceptions import MessageError
from gameplay.models import PlayerTroop, TroopRecruitment
from gameplay.services.recruitment.recruitment import finalize_troop_recruitment
from tests.troop_recruitment_service.support import build_due_recruitment

pytest_plugins = ("tests.troop_recruitment_service.conftest",)


@pytest.mark.django_db
def test_finalize_troop_recruitment_auto_creates_missing_troop_template(recruit_manor):
    manor = recruit_manor
    recruitment = build_due_recruitment(manor, troop_key="scout", troop_name="探子", quantity=3)

    assert finalize_troop_recruitment(recruitment, send_notification=False) is True

    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED

    template = TroopTemplate.objects.get(key="scout")
    troop = PlayerTroop.objects.get(manor=manor, troop_template=template)
    assert troop.count == 3


@pytest.mark.django_db
def test_finalize_troop_recruitment_keeps_success_when_explicit_failures(monkeypatch, recruit_manor):
    recruitment = build_due_recruitment(recruit_manor, troop_key="scout", troop_name="探子", quantity=2)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_troop_recruitment(recruitment, send_notification=True) is True
    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED


@pytest.mark.django_db
def test_finalize_troop_recruitment_message_runtime_marker_error_bubbles_up(monkeypatch, recruit_manor):
    recruitment = build_due_recruitment(recruit_manor, troop_key="scout", troop_name="探子", quantity=2)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_troop_recruitment(recruitment, send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED


@pytest.mark.django_db
def test_finalize_troop_recruitment_notification_runtime_marker_error_bubbles_up(monkeypatch, recruit_manor):
    recruitment = build_due_recruitment(recruit_manor, troop_key="scout", troop_name="探子", quantity=2)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_troop_recruitment(recruitment, send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED


@pytest.mark.django_db
def test_finalize_troop_recruitment_notification_programming_error_bubbles_up(monkeypatch, recruit_manor):
    recruitment = build_due_recruitment(recruit_manor, troop_key="scout", troop_name="探子", quantity=2)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken troop notify contract")),
    )

    with pytest.raises(AssertionError, match="broken troop notify contract"):
        finalize_troop_recruitment(recruitment, send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED
