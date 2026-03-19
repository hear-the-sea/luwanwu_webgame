from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.contrib import messages
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse

from core.exceptions import GameError
from core.utils import safe_positive_int, sanitize_error_message
from gameplay.models import ItemTemplate, Manor
from gameplay.services.buildings import forge as forge_service


def _parse_positive_quantity(raw_quantity: str | None) -> int | None:
    return safe_positive_int(raw_quantity, default=None)


def _normalize_forge_mode(raw_mode: str | None, *, default: str = "synthesize") -> str:
    mode = (raw_mode or default).strip()
    if mode not in {"synthesize", "decompose"}:
        return default
    return mode


def _forge_redirect_url(category: str, mode: str) -> str:
    return f"{reverse('gameplay:forge')}?mode={mode}&category={category}"


def _build_decompose_reward_text(result: dict[str, Any]) -> str:
    reward_map = result.get("rewards", {}) or {}
    reward_templates = {
        template.key: template.name
        for template in ItemTemplate.objects.filter(key__in=reward_map.keys()).only("key", "name")
    }
    reward_parts = [f"{reward_templates.get(key, key)}x{amount}" for key, amount in reward_map.items() if amount > 0]
    return f"，获得：{'、'.join(reward_parts)}" if reward_parts else ""


def run_forge_post_action(
    request,
    *,
    manor: Manor,
    item_key: str,
    raw_quantity: str | None,
    category: str,
    raw_mode: str | None,
    default_mode: str,
    missing_key_message: str,
    operation: Callable[[Manor, str, int], Any],
    success_message: Callable[[Any], str],
    on_database_error: Callable[[Exception], None],
) -> Any:
    quantity = _parse_positive_quantity(raw_quantity)
    mode = _normalize_forge_mode(raw_mode, default=default_mode)
    redirect_url = _forge_redirect_url(category, mode)

    if not item_key:
        messages.error(request, missing_key_message)
        return redirect(redirect_url)
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect(redirect_url)

    try:
        result = operation(manor, item_key, quantity)
        messages.success(request, success_message(result))
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except DatabaseError as exc:
        on_database_error(exc)

    return redirect(redirect_url)


def handle_start_equipment_forging(
    request, *, manor: Manor, category: str, on_database_error: Callable[[Exception], None]
):
    equipment_key = (request.POST.get("equipment_key") or "").strip()
    return run_forge_post_action(
        request,
        manor=manor,
        item_key=equipment_key,
        raw_quantity=request.POST.get("quantity"),
        category=category,
        raw_mode=request.POST.get("mode"),
        default_mode="synthesize",
        missing_key_message="请选择装备类型",
        operation=forge_service.start_equipment_forging,
        success_message=lambda production: (
            f"{production.equipment_name}"
            f"{'x' + str(production.quantity) if production.quantity > 1 else ''} 开始锻造，预计 {production.actual_duration} 秒后完成"
        ),
        on_database_error=on_database_error,
    )


def handle_decompose_equipment(request, *, manor: Manor, category: str, on_database_error: Callable[[Exception], None]):
    equipment_key = (request.POST.get("equipment_key") or "").strip()
    return run_forge_post_action(
        request,
        manor=manor,
        item_key=equipment_key,
        raw_quantity=request.POST.get("quantity"),
        category=category,
        raw_mode=request.POST.get("mode"),
        default_mode="decompose",
        missing_key_message="请选择要分解的装备",
        operation=forge_service.decompose_equipment,
        success_message=lambda result: (
            f"{result['equipment_name']}"
            f"{'x' + str(result['quantity']) if result['quantity'] > 1 else ''} 分解完成"
            f"{_build_decompose_reward_text(result)}"
        ),
        on_database_error=on_database_error,
    )


def handle_synthesize_blueprint_equipment(
    request,
    *,
    manor: Manor,
    category: str,
    on_database_error: Callable[[Exception], None],
):
    blueprint_key = (request.POST.get("blueprint_key") or "").strip()
    return run_forge_post_action(
        request,
        manor=manor,
        item_key=blueprint_key,
        raw_quantity=request.POST.get("quantity"),
        category=category,
        raw_mode=request.POST.get("mode"),
        default_mode="synthesize",
        missing_key_message="请选择图纸",
        operation=forge_service.synthesize_equipment_with_blueprint,
        success_message=lambda result: (
            f"{result['result_name']}" f"{'x' + str(result['quantity']) if result['quantity'] > 1 else ''} 合成完成"
        ),
        on_database_error=on_database_error,
    )
