"""
门客技能视图：学习技能、遗忘技能
"""

from __future__ import annotations

import logging
from typing import List

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.decorators import handle_game_errors
from core.exceptions import GameError
from core.utils.validation import safe_redirect_url, sanitize_error_message

from ..models import (
    Guest,
    GuestSkill,
    MAX_GUEST_SKILL_SLOTS,
    Skill,
)

logger = logging.getLogger(__name__)


@login_required
@require_POST
def learn_skill_view(request, pk: int):
    """
    学习技能视图

    由于有大量验证逻辑，保持手动错误处理以保持代码清晰
    但使用 manager 方法简化查询
    """
    from django.core.exceptions import ObjectDoesNotExist
    from gameplay.models import InventoryItem, ItemTemplate
    from gameplay.services.manor import ensure_manor

    manor = ensure_manor(request.user)
    # 使用 manager 方法获取门客，避免重复的 select_related
    guest = get_object_or_404(
        Guest.objects.for_manor(manor).with_template(),
        pk=pk
    )
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)

    item_id = request.POST.get("item_id")
    if not item_id:
        messages.error(request, "请选择技能书")
        return redirect(next_url)

    inventory_item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=item_id,
        template__effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    payload = inventory_item.template.effect_payload or {}
    skill_key = payload.get("skill_key")
    if not skill_key:
        messages.error(request, "技能书配置有误")
        return redirect(next_url)

    skill = get_object_or_404(Skill, key=skill_key)

    # 验证技能是否已学会
    if guest.guest_skills.filter(skill=skill).exists():
        messages.warning(request, f"{guest.display_name} 已掌握 {skill.name}")
        return redirect(next_url)

    # 验证技能位
    current_count = guest.guest_skills.count()
    if current_count >= MAX_GUEST_SKILL_SLOTS:
        messages.error(request, "技能位已满")
        return redirect(next_url)

    # 验证学习条件
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

    if unmet:
        messages.error(request, f"学习条件不足：{'，'.join(unmet)}")
        return redirect(next_url)

    # 使用事务确保原子性，并复用 consume_inventory_item 保证并发安全
    try:
        from gameplay.services.inventory import consume_inventory_item_locked

        with transaction.atomic():
            # 先加行锁，防止并发
            locked_item = (
                InventoryItem.objects.select_for_update()
                .filter(pk=inventory_item.pk)
                .first()
            )
            if not locked_item or locked_item.quantity < 1:
                raise ValueError("技能书数量不足")

            GuestSkill.objects.create(
                guest=guest,
                skill=skill,
                source=GuestSkill.Source.BOOK,
            )
            # locked_item 已持有行锁，直接在当前事务中扣减，避免嵌套事务开销
            consume_inventory_item_locked(locked_item)

        messages.success(request, f"{guest.display_name} 习得 {skill.name}")
    except (GameError, ValueError, ObjectDoesNotExist) as exc:
        logger.error(f"Failed to learn skill {skill.key} for guest {guest.id}: {exc}")
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(f"Unexpected error learning skill {skill.key} for guest {guest.id}: {exc}")
        messages.error(request, "学习技能失败，请稍后重试")
    return redirect(next_url)


@login_required
@require_POST
@handle_game_errors(redirect_url="guests:detail")
def forget_skill_view(request, pk: int):
    """
    遗忘技能视图

    使用统一装饰器处理错误
    """
    from gameplay.services.manor import ensure_manor

    # 使用 manager 方法获取门客，避免重复的 select_related
    guest = get_object_or_404(
        Guest.objects.for_manor(ensure_manor(request.user)).with_template(),
        pk=pk
    )

    guest_skill_id = request.POST.get("guest_skill_id")
    if not guest_skill_id:
        raise ValueError("未指定技能")

    guest_skill = get_object_or_404(guest.guest_skills.select_related("skill"), pk=guest_skill_id)
    skill_name = guest_skill.skill.name
    guest_skill.delete()

    messages.info(request, f"{guest.display_name} 已遗忘 {skill_name}")
    return reverse("guests:detail", args=[guest.pk])
