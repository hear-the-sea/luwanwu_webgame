import pytest
from django.utils import timezone

from core.exceptions import MessageError
from gameplay.models import PlayerTechnology
from gameplay.services.manor.core import ensure_manor, finalize_building_upgrade
from gameplay.services.technology import finalize_technology_upgrade


@pytest.mark.django_db
def test_finalize_building_upgrade_is_safe_with_stale_instances(django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_stale", password="pass12345")
    manor = ensure_manor(user)

    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    before_level = building.level
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    b1 = building.__class__.objects.get(pk=building.pk)
    b2 = building.__class__.objects.get(pk=building.pk)

    assert finalize_building_upgrade(b1, now=now, send_notification=False) is True
    assert finalize_building_upgrade(b2, now=now, send_notification=False) is False

    building.refresh_from_db()
    assert building.level == before_level + 1
    assert building.is_upgrading is False
    assert building.upgrade_complete_at is None


@pytest.mark.django_db
def test_finalize_technology_upgrade_is_safe_with_stale_instances(django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_stale", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    t1 = PlayerTechnology.objects.get(pk=tech.pk)
    t2 = PlayerTechnology.objects.get(pk=tech.pk)

    assert finalize_technology_upgrade(t1, send_notification=False) is True
    assert finalize_technology_upgrade(t2, send_notification=False) is False

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False
    assert tech.upgrade_complete_at is None


@pytest.mark.django_db
def test_finalize_building_upgrade_keeps_success_when_notification_fails(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_notify_fail", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    before_level = building.level
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )
    monkeypatch.setattr(
        "gameplay.services.manor.core.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_building_upgrade(building, now=now, send_notification=True) is True
    building.refresh_from_db()
    assert building.level == before_level + 1
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_message_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_msg_runtime", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_message_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_msg_programming", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken building message contract")),
    )

    with pytest.raises(AssertionError, match="broken building message contract"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_notification_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_ws_runtime", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.manor.core.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_notification_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_ws_programming", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.manor.core.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken building notify contract")),
    )

    with pytest.raises(AssertionError, match="broken building notify contract"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_keeps_success_when_notification_message_fails(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_notify_fail", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    def _raise_create_message(*_args, **_kwargs):
        raise MessageError("message backend down")

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", _raise_create_message)

    assert finalize_technology_upgrade(tech, send_notification=True) is True
    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_message_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_msg_runtime", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_message_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_msg_programming", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken technology message contract")),
    )

    with pytest.raises(AssertionError, match="broken technology message contract"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False
