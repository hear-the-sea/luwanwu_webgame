from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db.models import F
from django.db.models.functions import Least

from guests.models import Guest

MAX_GUEST_LOYALTY = 100


def _normalize_positive_int(raw: Any, *, field_name: str) -> int:
    if raw is None or isinstance(raw, bool):
        raise AssertionError(f"invalid guest loyalty {field_name}: {raw!r}")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid guest loyalty {field_name}: {raw!r}") from exc
    if value <= 0:
        raise AssertionError(f"invalid guest loyalty {field_name}: {raw!r}")
    return value


def extract_guest_ids(guests: Iterable[Any]) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for guest in guests:
        guest_id = getattr(guest, "pk", None) or getattr(guest, "id", None)
        if guest_id is None:
            continue
        parsed_id = _normalize_positive_int(guest_id, field_name="guest id")
        if parsed_id in seen:
            continue
        seen.add(parsed_id)
        normalized.append(parsed_id)
    return normalized


def increase_guest_loyalty_by_ids(guest_ids: Iterable[int], *, amount: int = 1) -> int:
    normalized_amount = _normalize_positive_int(amount, field_name="amount")

    normalized_ids: list[int] = []
    seen: set[int] = set()
    for guest_id in guest_ids:
        parsed_id = _normalize_positive_int(guest_id, field_name="guest id")
        if parsed_id in seen:
            continue
        seen.add(parsed_id)
        normalized_ids.append(parsed_id)

    if not normalized_ids:
        return 0

    return Guest.objects.filter(id__in=normalized_ids).update(
        loyalty=Least(MAX_GUEST_LOYALTY, F("loyalty") + normalized_amount)
    )


def grant_battle_victory_loyalty(guests: Iterable[Any], *, amount: int = 1) -> int:
    return increase_guest_loyalty_by_ids(extract_guest_ids(guests), amount=amount)
