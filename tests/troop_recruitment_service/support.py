from __future__ import annotations

import builtins
from datetime import timedelta

from django.utils import timezone

from battle.models import TroopTemplate
from gameplay.models import InventoryItem, ItemTemplate, TroopRecruitment


def create_tool_template(key: str, name: str) -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "effect_type": ItemTemplate.EffectType.TOOL,
            "effect_payload": {},
            "is_usable": True,
        },
    )
    return template


def set_inventory(manor, template: ItemTemplate, quantity: int) -> None:
    InventoryItem.objects.update_or_create(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": quantity},
    )


def build_due_recruitment(manor, *, troop_key: str = "scout", troop_name: str = "探子", quantity: int = 2):
    TroopTemplate.objects.filter(key=troop_key).delete()
    return TroopRecruitment.objects.create(
        manor=manor,
        troop_key=troop_key,
        troop_name=troop_name,
        quantity=quantity,
        equipment_costs={},
        retainer_cost=quantity,
        base_duration=60,
        actual_duration=60,
        complete_at=timezone.now() - timedelta(seconds=1),
    )


def patch_import(monkeypatch, handler):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        return handler(name, globals, locals, fromlist, level, original_import)

    monkeypatch.setattr(builtins, "__import__", _raising_import)


def missing_module_error(name: str, *, target: str | None = None) -> ModuleNotFoundError:
    error = ModuleNotFoundError(f"No module named '{name}'")
    error.name = target or name
    return error
