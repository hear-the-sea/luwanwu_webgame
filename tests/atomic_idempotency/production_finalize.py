import pytest
from django.utils import timezone

from core.exceptions import MessageError
from gameplay.services.buildings.ranch import finalize_livestock_production
from gameplay.services.buildings.smithy import finalize_smelting_production
from gameplay.services.buildings.stable import finalize_horse_production
from gameplay.services.manor.core import ensure_manor
from gameplay.services.technology import finalize_technology_upgrade
from tests.atomic_idempotency.support import PRODUCTION_NOTIFICATION_CASES, create_completed_notification_production


@pytest.mark.django_db
def test_finalize_technology_upgrade_keeps_success_when_notification_ws_fails(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_notify_ws_fail", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    from gameplay.models import PlayerTechnology

    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_technology_upgrade(tech, send_notification=True) is True
    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_notification_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_ws_runtime", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    from gameplay.models import PlayerTechnology

    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_notification_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_ws_programming", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    from gameplay.models import PlayerTechnology

    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken technology notify contract")),
    )

    with pytest.raises(AssertionError, match="broken technology notify contract"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.is_upgrading is False


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_path", "notify_user_path", "fields"),
    PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_message_programming_error_bubbles_up(
    _label,
    model_cls,
    finalize_path,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_msg_programming", password="pass12345")
    manor = ensure_manor(user)
    production = create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken production message contract")),
    )

    finalize_func = {
        "gameplay.services.buildings.stable.finalize_horse_production": finalize_horse_production,
        "gameplay.services.buildings.ranch.finalize_livestock_production": finalize_livestock_production,
        "gameplay.services.buildings.smithy.finalize_smelting_production": finalize_smelting_production,
    }[finalize_path]

    with pytest.raises(AssertionError, match="broken production message contract"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_path", "notify_user_path", "fields"),
    PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_keeps_success_when_message_infra_fails(
    _label,
    model_cls,
    finalize_path,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_msg_fail", password="pass12345")
    manor = ensure_manor(user)
    production = create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )

    finalize_func = {
        "gameplay.services.buildings.stable.finalize_horse_production": finalize_horse_production,
        "gameplay.services.buildings.ranch.finalize_livestock_production": finalize_livestock_production,
        "gameplay.services.buildings.smithy.finalize_smelting_production": finalize_smelting_production,
    }[finalize_path]

    assert finalize_func(production, send_notification=True) is True
    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_path", "notify_user_path", "fields"),
    PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_message_runtime_marker_error_bubbles_up(
    _label,
    model_cls,
    finalize_path,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_msg_runtime", password="pass12345")
    manor = ensure_manor(user)
    production = create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    finalize_func = {
        "gameplay.services.buildings.stable.finalize_horse_production": finalize_horse_production,
        "gameplay.services.buildings.ranch.finalize_livestock_production": finalize_livestock_production,
        "gameplay.services.buildings.smithy.finalize_smelting_production": finalize_smelting_production,
    }[finalize_path]

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_path", "notify_user_path", "fields"),
    PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_notification_programming_error_bubbles_up(
    _label,
    model_cls,
    finalize_path,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_ws_programming", password="pass12345")
    manor = ensure_manor(user)
    production = create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notify_user_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken production notify contract")),
    )

    finalize_func = {
        "gameplay.services.buildings.stable.finalize_horse_production": finalize_horse_production,
        "gameplay.services.buildings.ranch.finalize_livestock_production": finalize_livestock_production,
        "gameplay.services.buildings.smithy.finalize_smelting_production": finalize_smelting_production,
    }[finalize_path]

    with pytest.raises(AssertionError, match="broken production notify contract"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_path", "notify_user_path", "fields"),
    PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_keeps_success_when_notification_infra_fails(
    _label,
    model_cls,
    finalize_path,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_ws_fail", password="pass12345")
    manor = ensure_manor(user)
    production = create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notify_user_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    finalize_func = {
        "gameplay.services.buildings.stable.finalize_horse_production": finalize_horse_production,
        "gameplay.services.buildings.ranch.finalize_livestock_production": finalize_livestock_production,
        "gameplay.services.buildings.smithy.finalize_smelting_production": finalize_smelting_production,
    }[finalize_path]

    assert finalize_func(production, send_notification=True) is True
    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_path", "notify_user_path", "fields"),
    PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_notification_runtime_marker_error_bubbles_up(
    _label,
    model_cls,
    finalize_path,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_ws_runtime", password="pass12345")
    manor = ensure_manor(user)
    production = create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notify_user_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    finalize_func = {
        "gameplay.services.buildings.stable.finalize_horse_production": finalize_horse_production,
        "gameplay.services.buildings.ranch.finalize_livestock_production": finalize_livestock_production,
        "gameplay.services.buildings.smithy.finalize_smelting_production": finalize_smelting_production,
    }[finalize_path]

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED
