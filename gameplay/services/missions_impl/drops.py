from __future__ import annotations

import random
from typing import Dict, List

from ...models import InventoryItem, ItemTemplate, Manor, ResourceEvent, ResourceType
from ..resources import grant_resources


def award_mission_drops(manor: Manor, drops: Dict[str, int], note: str) -> None:
    if not drops:
        return

    resource_keys = set(ResourceType.values)
    resources = {k: v for k, v in drops.items() if k in resource_keys}
    item_keys = {k: v for k, v in drops.items() if k not in resource_keys}
    if resources:
        grant_resources(manor, resources, note, ResourceEvent.Reason.BATTLE_REWARD)

    if not item_keys:
        return

    from guests.models import SkillBook

    templates = {it.key: it for it in ItemTemplate.objects.filter(key__in=item_keys.keys())}
    missing_keys = set(item_keys.keys()) - set(templates.keys())
    if missing_keys:
        books = {book.key: book for book in SkillBook.objects.filter(key__in=missing_keys)}
        for key in list(missing_keys):
            book = books.get(key)
            if not book:
                continue
            tmpl, _ = ItemTemplate.objects.get_or_create(
                key=key,
                defaults={
                    "name": book.name,
                    "description": book.description,
                    "effect_type": ItemTemplate.EffectType.SKILL_BOOK,
                    "effect_payload": {"skill_key": book.skill.key, "skill_name": book.skill.name},
                },
            )
            templates[key] = tmpl

    template_ids = [templates[key].id for key in item_keys.keys() if key in templates]
    existing_items = {
        item.template_id: item
        for item in InventoryItem.objects.filter(
            manor=manor,
            template_id__in=template_ids,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
    }

    to_update: List[InventoryItem] = []
    to_create: List[InventoryItem] = []
    for key, amount in item_keys.items():
        template = templates.get(key)
        if not template:
            continue
        existing_item = existing_items.get(template.id)
        if existing_item:
            existing_item.quantity += amount
            to_update.append(existing_item)
        else:
            to_create.append(
                InventoryItem(
                    manor=manor,
                    template=template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                    quantity=amount,
                )
            )

    if to_create:
        InventoryItem.objects.bulk_create(to_create)
    if to_update:
        InventoryItem.objects.bulk_update(to_update, ["quantity"])


def resolve_defense_drops_if_missing(report, mission_drop_table: dict) -> dict:
    """Defense missions may generate a report without drops; fill them deterministically."""
    drops = dict(report.drops or {})
    if drops:
        return drops

    from common.utils.loot import resolve_drop_rewards

    seed = getattr(report, "seed", None)
    rng = random.Random(seed) if seed is not None else random.Random()
    return resolve_drop_rewards(mission_drop_table or {}, rng)
