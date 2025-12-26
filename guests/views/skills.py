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

from core.utils import safe_redirect_url, sanitize_error_message
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services import ensure_manor

from ..models import (
    GuestSkill,
    MAX_GUEST_SKILL_SLOTS,
    Skill,
)

logger = logging.getLogger(__name__)


@login_required
@require_POST
def learn_skill_view(request, pk: int):
    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests.select_related("template"), pk=pk)
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
    if guest.guest_skills.filter(skill=skill).exists():
        messages.warning(request, f"{guest.display_name} 已掌握 {skill.name}")
        return redirect(next_url)
    current_count = guest.guest_skills.count()
    if current_count >= MAX_GUEST_SKILL_SLOTS:
        messages.error(request, "技能位已满")
        return redirect(next_url)
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
    try:
        with transaction.atomic():
            GuestSkill.objects.create(
                guest=guest,
                skill=skill,
                source=GuestSkill.Source.BOOK,
            )
            inventory_item.quantity -= 1
            if inventory_item.quantity <= 0:
                inventory_item.delete()
            else:
                inventory_item.save(update_fields=["quantity"])
        messages.success(request, f"{guest.display_name} 习得 {skill.name}")
    except Exception as exc:
        logger.exception(f"Failed to learn skill {skill.key} for guest {guest.id}: {exc}")
        messages.error(request, sanitize_error_message(exc))
    return redirect(next_url)


@login_required
@require_POST
def forget_skill_view(request, pk: int):
    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests.select_related("template"), pk=pk)
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    guest_skill_id = request.POST.get("guest_skill_id")
    if not guest_skill_id:
        messages.error(request, "未指定技能")
        return redirect(next_url)
    guest_skill = get_object_or_404(guest.guest_skills.select_related("skill"), pk=guest_skill_id)
    skill_name = guest_skill.skill.name
    guest_skill.delete()
    messages.info(request, f"{guest.display_name} 已遗忘 {skill_name}")
    return redirect(next_url)
