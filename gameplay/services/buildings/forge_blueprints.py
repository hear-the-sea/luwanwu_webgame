from __future__ import annotations

from typing import Any

from django.db import transaction

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.models import Manor as ManorModel

from .. import technology as technology_service
from ..inventory.core import add_item_to_inventory_locked, consume_inventory_item_locked
from .forge_helpers import build_blueprint_synthesis_option, build_inventory_quantity_map, collect_recipe_related_keys


def build_blueprint_recipe_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for recipe in config.get("recipes", []) or []:
        key = str(recipe.get("blueprint_key") or "").strip()
        if key:
            result[key] = recipe
    return result


def get_blueprint_synthesis_options(
    manor: Any,
    *,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    recipes = config.get("recipes", []) or []
    if not recipes:
        return []

    all_keys = collect_recipe_related_keys(recipes)
    template_map = {tpl.key: tpl for tpl in ItemTemplate.objects.filter(key__in=all_keys)}
    inventory_items = (
        InventoryItem.objects.filter(
            manor=manor,
            template__key__in=all_keys,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .select_related("template")
        .order_by("id")
    )
    quantities = build_inventory_quantity_map(inventory_items)
    forging_level = technology_service.get_player_technology_level(manor, "forging")

    options: list[dict[str, Any]] = []
    for recipe in recipes:
        option = build_blueprint_synthesis_option(
            recipe,
            quantities=quantities,
            template_map=template_map,
            forging_level=forging_level,
        )
        if option is not None:
            options.append(option)

    options.sort(key=lambda row: (row["required_forging"], row["result_name"]), reverse=True)
    return options


def synthesize_equipment_with_blueprint(
    manor: Any,
    blueprint_key: str,
    quantity: int = 1,
    *,
    recipe_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if quantity < 1:
        raise ValueError("合成数量至少为1")

    recipe = recipe_index.get(blueprint_key)
    if not recipe:
        raise ValueError("无效的图纸")

    required_forging = int(recipe.get("required_forging", 1))
    forging_level = technology_service.get_player_technology_level(manor, "forging")
    if forging_level < required_forging:
        raise ValueError(f"需要锻造技{required_forging}级才能合成")

    result_item_key = recipe["result_item_key"]
    result_template = ItemTemplate.objects.filter(key=result_item_key).only("key", "name", "effect_type").first()
    if not result_template:
        raise ValueError("图纸配置错误：产物不存在")
    if not str(result_template.effect_type or "").startswith("equip_"):
        raise ValueError("图纸配置错误：产物必须是装备")

    consume_requirements: dict[str, int] = {blueprint_key: quantity}
    for cost_key, cost_amount in recipe.get("costs", {}).items():
        total = int(cost_amount) * quantity
        consume_requirements[cost_key] = consume_requirements.get(cost_key, 0) + total

    template_names = {
        tpl.key: tpl.name
        for tpl in ItemTemplate.objects.filter(key__in=consume_requirements.keys()).only("key", "name")
    }

    with transaction.atomic():
        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)
        locked_items = {
            item.template.key: item
            for item in InventoryItem.objects.select_for_update()
            .select_related("template")
            .filter(
                manor=locked_manor,
                template__key__in=consume_requirements.keys(),
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
        }

        for need_key, need_amount in consume_requirements.items():
            item = locked_items.get(need_key)
            if not item or item.quantity < need_amount:
                need_name = template_names.get(need_key, need_key)
                raise ValueError(f"{need_name}不足")

        for need_key, need_amount in consume_requirements.items():
            consume_inventory_item_locked(locked_items[need_key], need_amount)

        output_quantity = int(recipe.get("quantity_out", 1)) * quantity
        add_item_to_inventory_locked(locked_manor, result_item_key, output_quantity)

    return {
        "blueprint_key": blueprint_key,
        "result_key": result_item_key,
        "result_name": result_template.name,
        "quantity": output_quantity,
        "craft_times": quantity,
    }
