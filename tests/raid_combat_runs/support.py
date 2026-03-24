from __future__ import annotations

from gameplay.services.manor.core import ensure_manor


def build_attacker_defender(django_user_model, *, attacker_username: str, defender_username: str):
    attacker = ensure_manor(django_user_model.objects.create_user(username=attacker_username, password="pass123"))
    defender = ensure_manor(django_user_model.objects.create_user(username=defender_username, password="pass123"))
    return attacker, defender
