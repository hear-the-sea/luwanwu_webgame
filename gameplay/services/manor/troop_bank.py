"""
护院钱庄服务
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Sum

from ...models import Manor, PlayerTroop, TroopBankStorage

TROOP_BANK_CAPACITY = 5000


def _normalize_positive_quantity(quantity: int, *, action: str) -> int:
    try:
        normalized = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{action}数量必须是正整数") from exc
    if normalized <= 0:
        raise ValueError(f"{action}数量必须大于0")
    return normalized


def get_troop_bank_capacity(_manor: Manor | None = None) -> int:
    return TROOP_BANK_CAPACITY


def get_troop_bank_used_space(manor: Manor) -> int:
    used = TroopBankStorage.objects.filter(manor=manor).aggregate(total=Sum("count")).get("total") or 0
    return max(0, int(used))


def get_troop_bank_remaining_space(manor: Manor) -> int:
    return max(0, TROOP_BANK_CAPACITY - get_troop_bank_used_space(manor))


def get_troop_bank_rows(manor: Manor) -> list[dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}

    player_troops = (
        PlayerTroop.objects.filter(manor=manor, count__gt=0)
        .select_related("troop_template")
        .order_by("troop_template__priority")
    )
    bank_troops = (
        TroopBankStorage.objects.filter(manor=manor, count__gt=0)
        .select_related("troop_template")
        .order_by("troop_template__priority")
    )

    for player_troop in player_troops:
        template = player_troop.troop_template
        rows_by_key[template.key] = {
            "key": template.key,
            "name": template.name,
            "avatar": template.avatar.url if template.avatar else "",
            "priority": template.priority,
            "player_count": player_troop.count,
            "bank_count": 0,
        }

    for bank_troop in bank_troops:
        template = bank_troop.troop_template
        row = rows_by_key.setdefault(
            template.key,
            {
                "key": template.key,
                "name": template.name,
                "avatar": template.avatar.url if template.avatar else "",
                "priority": template.priority,
                "player_count": 0,
                "bank_count": 0,
            },
        )
        row["bank_count"] = bank_troop.count

    rows = list(rows_by_key.values())
    rows.sort(key=lambda row: (row.get("priority", 0), row.get("key", "")))
    return rows


def _lock_manor(manor: Manor) -> Manor:
    return Manor.objects.select_for_update().get(pk=manor.pk)


@transaction.atomic
def deposit_troops_to_bank(manor: Manor, troop_key: str, quantity: int) -> dict[str, Any]:
    quantity = _normalize_positive_quantity(quantity, action="存入")

    locked_manor = _lock_manor(manor)

    player_troop = (
        PlayerTroop.objects.select_for_update()
        .filter(manor=locked_manor, troop_template__key=troop_key)
        .select_related("troop_template")
        .first()
    )
    if not player_troop:
        raise ValueError("没有该类型的护院")
    if player_troop.count < quantity:
        raise ValueError(f"{player_troop.troop_template.name}数量不足，当前可用{player_troop.count}")

    used = get_troop_bank_used_space(locked_manor)
    if used + quantity > TROOP_BANK_CAPACITY:
        raise ValueError(f"钱庄护院容量不足，最多可存放{TROOP_BANK_CAPACITY}名")

    bank_troop, _created = TroopBankStorage.objects.get_or_create(
        manor=locked_manor,
        troop_template=player_troop.troop_template,
        defaults={"count": 0},
    )
    bank_troop.count += quantity
    bank_troop.save(update_fields=["count", "updated_at"])

    player_troop.count -= quantity
    player_troop.save(update_fields=["count", "updated_at"])

    return {
        "troop_name": player_troop.troop_template.name,
        "quantity": quantity,
        "used": used + quantity,
        "capacity": TROOP_BANK_CAPACITY,
    }


@transaction.atomic
def withdraw_troops_from_bank(manor: Manor, troop_key: str, quantity: int) -> dict[str, Any]:
    quantity = _normalize_positive_quantity(quantity, action="取出")

    locked_manor = _lock_manor(manor)

    bank_troop = (
        TroopBankStorage.objects.select_for_update()
        .filter(manor=locked_manor, troop_template__key=troop_key)
        .select_related("troop_template")
        .first()
    )
    if not bank_troop:
        raise ValueError("钱庄中没有该类型护院")
    if bank_troop.count < quantity:
        raise ValueError(f"钱庄中{bank_troop.troop_template.name}数量不足，当前仅有{bank_troop.count}")

    player_troop, _created = PlayerTroop.objects.get_or_create(
        manor=locked_manor,
        troop_template=bank_troop.troop_template,
        defaults={"count": 0},
    )
    player_troop.count += quantity
    player_troop.save(update_fields=["count", "updated_at"])

    bank_troop.count -= quantity
    if bank_troop.count <= 0:
        bank_troop.delete()
    else:
        bank_troop.save(update_fields=["count", "updated_at"])

    return {
        "troop_name": player_troop.troop_template.name,
        "quantity": quantity,
        "used": get_troop_bank_used_space(locked_manor),
        "capacity": TROOP_BANK_CAPACITY,
    }
