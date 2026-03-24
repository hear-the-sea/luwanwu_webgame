from __future__ import annotations

from types import SimpleNamespace

from django.contrib.messages import get_messages
from django.urls import reverse

from gameplay.services.manor.core import ensure_manor


def response_messages(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def message_objects(response):
    return list(get_messages(response.wsgi_request))


def build_manor(django_user_model, *, username: str):
    return ensure_manor(django_user_model.objects.get(username=username))


def build_prisoner_context():
    return [
        SimpleNamespace(
            id=1,
            display_name="prisoner-a",
            guest_template=SimpleNamespace(rarity="green"),
            loyalty=20,
            original_manor=SimpleNamespace(display_name="旧主"),
            captured_at=None,
        )
    ]


def build_bond_context():
    return [
        SimpleNamespace(
            guest_id=2,
            guest=SimpleNamespace(display_name="bond-a", template=SimpleNamespace(rarity="blue"), level=9),
            created_at=None,
        )
    ]


def build_available_guests():
    return [SimpleNamespace(id=3, display_name="guest-a", template=SimpleNamespace(rarity="green"), level=5)]


def jail_url() -> str:
    return reverse("gameplay:jail")


def oath_url() -> str:
    return reverse("gameplay:oath_grove")
