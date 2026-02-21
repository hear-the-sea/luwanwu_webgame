from __future__ import annotations

import random
from typing import Dict

from django.db import IntegrityError, transaction
from django.db.models import F

from ...models import InventoryItem, ItemTemplate, Manor, ResourceEvent, ResourceType
from ..resources import grant_resources_locked


def _split_drop_payload(drops: Dict[str, int]) -> tuple[Dict[str, int], Dict[str, int]]:
    resource_keys = set(ResourceType.values)
    resources = {k: v for k, v in drops.items() if k in resource_keys}
    items = {k: v for k, v in drops.items() if k not in resource_keys}
    return resources, items


def _load_item_templates_with_skillbook_fallback(item_keys: Dict[str, int]) -> Dict[str, ItemTemplate]:
    if not item_keys:
        return {}

    from guests.models import SkillBook

    templates = {it.key: it for it in ItemTemplate.objects.filter(key__in=item_keys.keys())}
    missing_keys = set(item_keys.keys()) - set(templates.keys())
    if not missing_keys:
        return templates

    books = {book.key: book for book in SkillBook.objects.filter(key__in=missing_keys)}
    for key in list(missing_keys):
        book = books.get(key)
        if not book:
            continue
        tmpl = _get_or_create_skill_book_template(key, book)
        templates[key] = tmpl
    return templates


def _get_or_create_skill_book_template(key: str, book) -> ItemTemplate:
    defaults = {
        "name": book.name,
        "description": book.description,
        "effect_type": ItemTemplate.EffectType.SKILL_BOOK,
        "effect_payload": {"skill_key": book.skill.key, "skill_name": book.skill.name},
    }
    try:
        tmpl, _ = ItemTemplate.objects.get_or_create(key=key, defaults=defaults)
        return tmpl
    except IntegrityError:
        # Another concurrent transaction may have created this template.
        existing = ItemTemplate.objects.filter(key=key).first()
        if existing:
            return existing
        raise


def _upsert_warehouse_items_locked(manor: Manor, item_keys: Dict[str, int], templates: Dict[str, ItemTemplate]) -> None:
    for key, amount in item_keys.items():
        if amount <= 0:
            continue

        template = templates.get(key)
        if not template:
            continue

        inventory_item, _created = (
            InventoryItem.objects.select_for_update()
            .get_or_create(
                manor=manor,
                template=template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                defaults={"quantity": 0},
            )
        )
        InventoryItem.objects.filter(pk=inventory_item.pk).update(quantity=F("quantity") + amount)


def award_mission_drops_locked(
    manor: Manor,
    drops: Dict[str, int],
    note: str,
    *,
    locked_manor: Manor | None = None,
) -> None:
    if not drops:
        return

    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("award_mission_drops_locked must be called inside transaction.atomic()")

    manor_locked = locked_manor or Manor.objects.select_for_update().get(pk=manor.pk)

    resources, item_keys = _split_drop_payload(drops)
    if resources:
        grant_resources_locked(manor_locked, resources, note, ResourceEvent.Reason.BATTLE_REWARD)

    if not item_keys:
        return

    templates = _load_item_templates_with_skillbook_fallback(item_keys)
    _upsert_warehouse_items_locked(manor_locked, item_keys, templates)


def award_mission_drops(manor: Manor, drops: Dict[str, int], note: str) -> None:
    if not drops:
        return

    with transaction.atomic():
        locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
        award_mission_drops_locked(manor, drops, note, locked_manor=locked_manor)


def resolve_defense_drops_if_missing(report, mission_drop_table: dict) -> dict:
    """Defense missions may generate a report without drops; fill them deterministically."""
    drops = dict(report.drops or {})
    if drops:
        return drops

    from common.utils.loot import resolve_drop_rewards

    seed = getattr(report, "seed", None)
    rng = random.Random(seed) if seed is not None else random.Random()
    return resolve_drop_rewards(mission_drop_table or {}, rng)
