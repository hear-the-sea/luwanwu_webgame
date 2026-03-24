from __future__ import annotations

from django.contrib.messages import get_messages
from django.utils import timezone

from gameplay.models import ScoutRecord
from gameplay.services.manor.core import ensure_manor


def response_messages(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def assert_redirect(response, url: str) -> None:
    assert response.status_code == 302
    assert response.url == url


def build_scout_record(*, attacker, django_user_model, username: str):
    defender_user = django_user_model.objects.create_user(username=username, password="pass123")
    defender = ensure_manor(defender_user)
    return ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        complete_at=timezone.now(),
    )
