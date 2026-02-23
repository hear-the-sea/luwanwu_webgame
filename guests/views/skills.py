"""
门客技能视图：学习技能、遗忘技能
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.decorators import handle_game_errors
from core.exceptions import GameError
from core.utils.validation import safe_positive_int, safe_redirect_url, sanitize_error_message

from ..models import MAX_GUEST_SKILL_SLOTS, Guest, GuestSkill, GuestStatus, Skill

logger = logging.getLogger(__name__)


def _get_guest_and_next_url(request, pk: int):
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(request.user)
    guest = get_object_or_404(Guest.objects.for_manor(manor).with_template(), pk=pk)
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    return manor, guest, next_url


def _get_skill_book_inventory_item(manor, item_id: int):
    from gameplay.models import InventoryItem, ItemTemplate

    return get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=item_id,
        template__effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


def _resolve_skill_from_inventory_item(inventory_item) -> Skill | None:
    payload = inventory_item.template.effect_payload or {}
    skill_key = str(payload.get("skill_key", "")).strip()
    if not skill_key:
        return None
    return Skill.objects.filter(key=skill_key).first()


def _collect_unmet_skill_requirements(guest: Guest, skill: Skill) -> List[str]:
    unmet: List[str] = []
    if skill.required_level and guest.level < skill.required_level:
        unmet.append(f"等级需 ≥ {skill.required_level}")
    if skill.required_force and guest.force < skill.required_force:
        unmet.append(f"武力需 ≥ {skill.required_force}")
    if skill.required_intellect and guest.intellect < skill.required_intellect:
        unmet.append(f"智力需 ≥ {skill.required_intellect}")
    if skill.required_defense and guest.defense_stat < skill.required_defense:
        unmet.append(f"防御需 ≥ {skill.required_defense}")
    if skill.required_agility and guest.agility < skill.required_agility:
        unmet.append(f"敏捷需 ≥ {skill.required_agility}")
    return unmet


def _validate_learn_skill_preconditions(guest: Guest, skill: Skill) -> Tuple[str, str] | None:
    if guest.status != GuestStatus.IDLE:
        return "error", f"{guest.display_name} 当前非空闲状态，无法学习技能"

    if guest.guest_skills.filter(skill=skill).exists():
        return "warning", f"{guest.display_name} 已掌握 {skill.name}"

    if guest.guest_skills.count() >= MAX_GUEST_SKILL_SLOTS:
        return "error", "技能位已满"

    unmet = _collect_unmet_skill_requirements(guest, skill)
    if unmet:
        return "error", f"学习条件不足：{'，'.join(unmet)}"

    return None


def _persist_skill_learning(guest: Guest, skill: Skill, inventory_item) -> None:
    from gameplay.models import InventoryItem
    from gameplay.services.inventory import consume_inventory_item_locked

    with transaction.atomic():
        # Lock guest to prevent concurrent skill learning exceeding limits
        locked_guest = Guest.objects.select_for_update().get(pk=guest.pk)
        if locked_guest.status != GuestStatus.IDLE:
            raise ValueError(f"{locked_guest.display_name} 当前非空闲状态，无法学习技能")

        if locked_guest.guest_skills.count() >= MAX_GUEST_SKILL_SLOTS:
            raise ValueError("技能位已满")

        if locked_guest.guest_skills.filter(skill=skill).exists():
            raise ValueError(f"{locked_guest.display_name} 已掌握 {skill.name}")

        locked_item = InventoryItem.objects.select_for_update().filter(pk=inventory_item.pk).first()
        if not locked_item or locked_item.quantity < 1:
            raise ValueError("技能书数量不足")

        GuestSkill.objects.create(
            guest=locked_guest,
            skill=skill,
            source=GuestSkill.Source.BOOK,
        )
        consume_inventory_item_locked(locked_item)


def _persist_skill_forget(guest: Guest, guest_skill_id: int) -> str:
    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().select_related("template").filter(pk=guest.pk).first()
        if locked_guest is None:
            raise ValueError("门客不存在")
        if locked_guest.status != GuestStatus.IDLE:
            raise ValueError(f"{locked_guest.display_name} 当前非空闲状态，无法遗忘技能")

        locked_guest_skill = locked_guest.guest_skills.select_related("skill").filter(pk=guest_skill_id).first()
        if locked_guest_skill is None:
            raise ValueError("未找到要遗忘的技能")

        skill_name = locked_guest_skill.skill.name
        locked_guest_skill.delete()
        return skill_name


@login_required
@require_POST
def learn_skill_view(request, pk: int):
    """
    学习技能视图

    由于有大量验证逻辑，保持手动错误处理以保持代码清晰
    但使用 manager 方法简化查询
    """
    from django.core.exceptions import ObjectDoesNotExist

    manor, guest, next_url = _get_guest_and_next_url(request, pk)

    item_id = request.POST.get("item_id")
    item_id_int = safe_positive_int(item_id, default=None)
    if item_id_int is None:
        messages.error(request, "请选择技能书")
        return redirect(next_url)

    inventory_item = _get_skill_book_inventory_item(manor, item_id_int)
    skill = _resolve_skill_from_inventory_item(inventory_item)
    if skill is None:
        messages.error(request, "技能书配置有误")
        return redirect(next_url)

    precondition_error = _validate_learn_skill_preconditions(guest, skill)
    if precondition_error is not None:
        level, message = precondition_error
        if level == "warning":
            messages.warning(request, message)
        else:
            messages.error(request, message)
        return redirect(next_url)

    try:
        _persist_skill_learning(guest, skill, inventory_item)
        messages.success(request, f"{guest.display_name} 习得 {skill.name}")
    except (GameError, ValueError, ObjectDoesNotExist) as exc:
        logger.warning(
            "Skill learn rejected: manor_id=%s user_id=%s guest_id=%s item_id=%s skill_key=%s error=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            getattr(guest, "id", None),
            item_id_int,
            getattr(skill, "key", None),
            exc,
        )
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected skill learn error: manor_id=%s user_id=%s guest_id=%s item_id=%s skill_key=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            getattr(guest, "id", None),
            item_id_int,
            getattr(skill, "key", None),
        )
        messages.error(request, sanitize_error_message(exc))
    return redirect(next_url)


@login_required
@require_POST
@handle_game_errors(redirect_url="guests:detail")
def forget_skill_view(request, pk: int):
    """
    遗忘技能视图

    使用统一装饰器处理错误
    """
    from gameplay.services.manor.core import ensure_manor

    # 使用 manager 方法获取门客，避免重复的 select_related
    guest = get_object_or_404(Guest.objects.for_manor(ensure_manor(request.user)).with_template(), pk=pk)

    guest_skill_id = safe_positive_int(request.POST.get("guest_skill_id"), default=None)
    if guest_skill_id is None:
        raise ValueError("未指定技能")

    skill_name = _persist_skill_forget(guest, guest_skill_id)

    messages.info(request, f"{guest.display_name} 已遗忘 {skill_name}")
    return reverse("guests:detail", args=[guest.pk])
