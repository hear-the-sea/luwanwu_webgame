from __future__ import annotations

import uuid
from datetime import timedelta

from django.utils import timezone

from gameplay.services.manor.core import ensure_manor


def prepare_attack_ready_manors(django_user_model, *, prefix: str):
    attacker_user = django_user_model.objects.create_user(
        username=f"{prefix}_attacker_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    defender_user = django_user_model.objects.create_user(
        username=f"{prefix}_defender_{uuid.uuid4().hex[:8]}",
        password="pass123",
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    for manor in (attacker, defender):
        manor.newbie_protection_until = timezone.now() - timedelta(days=1)
        manor.peace_shield_until = None
        manor.defeat_protection_until = None
        manor.prestige = 100
        manor.grain = 500000
        manor.silver = 500000
        manor.save(
            update_fields=[
                "newbie_protection_until",
                "peace_shield_until",
                "defeat_protection_until",
                "prestige",
                "grain",
                "silver",
            ]
        )

    return attacker, defender
