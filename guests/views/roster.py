"""
门客名册视图：列表、详情、辞退
"""

from __future__ import annotations

import logging
from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import sanitize_error_message
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services import ensure_manor, refresh_manor_state

from ..constants import TimeConstants
from ..forms import AllocateSkillPointsForm
from ..models import (
    GearItem,
    GearSlot,
    GearTemplate,
    GuestSkill,
    GuestStatus,
    MAX_GUEST_SKILL_SLOTS,
    Skill,
)
from ..services import available_guests, finalize_guest_training, recover_guest_hp
from ..utils.guest_state import refresh_guests_state

logger = logging.getLogger(__name__)


class RosterView(LoginRequiredMixin, TemplateView):
    template_name = "guests/roster.html"

    def get_context_data(self, **kwargs):
        from guests.services.salary import get_guest_salary, bulk_check_salary_paid, get_unpaid_guests

        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        guests = list(available_guests(manor))
        refresh_guests_state(guests, now=timezone.now(), refresh=True)
        exp_items = list(
            manor.inventory_items.select_related("template").filter(
                template__effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
        )
        medicine_items = list(
            manor.inventory_items.select_related("template").filter(
                template__effect_type=ItemTemplate.EffectType.MEDICINE,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
        )

        # 添加工资相关信息（优化 N+1：批量查询已支付状态）
        today = timezone.now().date()
        guest_ids = [g.id for g in guests]
        paid_ids = bulk_check_salary_paid(guest_ids, today)

        guests_with_salary = []
        for guest in guests:
            guest_salary = get_guest_salary(guest)
            guest_paid = guest.id in paid_ids
            guests_with_salary.append({
                "guest": guest,
                "salary": guest_salary,
                "paid_today": guest_paid,
            })

        unpaid_guests = get_unpaid_guests(manor, today)
        total_unpaid_salary = sum(get_guest_salary(g) for g in unpaid_guests)

        context["manor"] = manor
        context["guests"] = guests
        context["guests_with_salary"] = guests_with_salary
        context["unpaid_count"] = len(unpaid_guests)
        context["total_unpaid_salary"] = total_unpaid_salary
        context["exp_items"] = exp_items
        context["medicine_items"] = medicine_items
        return context


class GuestDetailView(LoginRequiredMixin, TemplateView):
    template_name = "guests/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        guest = get_object_or_404(
            manor.guests.select_related("template").prefetch_related(
                Prefetch(
                    "gear_items",
                    queryset=GearItem.objects.select_related("template").only(
                        "id",
                        "guest_id",
                        "template_id",
                        "template__slot",
                        "template__name",
                        "template__rarity",
                        "template__set_key",
                        "template__set_description",
                        "template__set_bonus",
                        "template__attack_bonus",
                        "template__defense_bonus",
                        "template__extra_stats",
                    ),
                ),
                Prefetch(
                    "guest_skills",
                    queryset=GuestSkill.objects.select_related("skill").only(
                        "id",
                        "guest_id",
                        "skill_id",
                        "learned_at",
                        "skill__key",
                        "skill__name",
                        "skill__description",
                    ),
                ),
            ),
            pk=self.kwargs["pk"],
        )
        now = timezone.now()
        needs_refresh = False
        if guest.training_complete_at and guest.training_complete_at <= now:
            if finalize_guest_training(guest, now=now):
                needs_refresh = True
        if guest.status != GuestStatus.INJURED and guest.current_hp < guest.max_hp:
            last = guest.last_hp_recovery_at or guest.created_at or now
            if (now - last).total_seconds() >= TimeConstants.HP_RECOVERY_INTERVAL:
                recover_guest_hp(guest, now=now)
                needs_refresh = True
        if needs_refresh:
            guest.refresh_from_db()
        slots = [(choice.value, choice.label) for choice in GearSlot]
        slot_capacity = {
            GearSlot.DEVICE.value: 3,
            GearSlot.ORNAMENT.value: 3,
        }
        gear_items = list(guest.gear_items.all())
        equipped = {slot: [] for slot, _ in slots}
        for item in gear_items:
            equipped[item.template.slot].append(item)

        guest_skill_records = sorted(
            guest.guest_skills.all(),
            key=lambda record: (record.learned_at, record.id),
        )
        # 套装详情
        equipped_templates = [item.template for item in gear_items]
        set_keys = {tpl.set_key for tpl in equipped_templates if getattr(tpl, "set_key", "")}
        gear_sets = []
        gear_set_map = {}
        if set_keys:
            templates = list(
                GearTemplate.objects.filter(set_key__in=set_keys)
                .only("id", "name", "set_key", "set_description", "set_bonus", "rarity", "slot")
                .order_by("set_key", "slot", "id")
            )
            templates_by_set = {}
            for tpl in templates:
                templates_by_set.setdefault(tpl.set_key, []).append(tpl)
            equipped_ids = {tpl.id for tpl in equipped_templates}
            for set_key in sorted(templates_by_set):
                members = templates_by_set.get(set_key, [])
                if not members:
                    continue
                bonus = members[0].set_bonus or {}
                members_payload = [
                    {
                        "id": tpl.id,
                        "name": tpl.name,
                        "slot": tpl.get_slot_display() if hasattr(tpl, "get_slot_display") else tpl.slot,
                        "rarity": tpl.rarity,
                        "equipped": tpl.id in equipped_ids,
                    }
                    for tpl in members
                ]
                set_desc = members[0].set_description if hasattr(members[0], "set_description") else ""
                gear_sets.append(
                    {
                        "key": set_key,
                        "description": set_desc,
                        "pieces": bonus.get("pieces"),
                        "bonus": bonus.get("bonus") or bonus,
                        "members": members_payload,
                    }
                )
                gear_set_map[set_key] = {
                    "description": set_desc,
                    "pieces": bonus.get("pieces"),
                    "bonus": bonus.get("bonus") or bonus,
                    "members": members_payload,
                }
        skill_slots = []
        for idx in range(MAX_GUEST_SKILL_SLOTS):
            record = guest_skill_records[idx] if idx < len(guest_skill_records) else None
            skill_slots.append(
                {
                    "index": idx + 1,
                    "record": record,
                    "skill": record.skill if record else None,
                }
            )
        skill_books = []
        if len(guest_skill_records) < MAX_GUEST_SKILL_SLOTS:
            skill_book_items = (
                manor.inventory_items.filter(
                    template__effect_type=ItemTemplate.EffectType.SKILL_BOOK,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                )
                .select_related("template")
                .only("id", "quantity", "template__name", "template__effect_payload")
                .order_by("template__name")
            )
            skill_keys = {
                (item.template.effect_payload or {}).get("skill_key")
                for item in skill_book_items
                if (item.template.effect_payload or {}).get("skill_key")
            }
            skills = {
                skill.key: skill
                for skill in Skill.objects.filter(key__in=skill_keys).only("key", "name", "description")
            }
            for entry in skill_book_items:
                payload = entry.template.effect_payload or {}
                key = payload.get("skill_key")
                skill_books.append(
                    {
                        "inventory": entry,
                        "skill": skills.get(key),
                        "skill_key": key,
                    }
                )
        slot_panels = []
        for slot, label in slots:
            equipped_list = equipped.get(slot) or []
            capacity = slot_capacity.get(slot, 1)
            positions = []
            for idx in range(capacity):
                positions.append(equipped_list[idx] if idx < len(equipped_list) else None)
            slot_panels.append(
                {
                    "value": slot,
                    "label": label,
                    "equipped": equipped_list,
                    "positions": positions,
                    "options": [],
                    "capacity": capacity,
                }
            )
        context.update(
            {
                "guest": guest,
                "slot_panels": slot_panels,
                "slot_panels_map": {panel["value"]: panel for panel in slot_panels},
                "skill_slots": skill_slots,
                "skill_capacity": MAX_GUEST_SKILL_SLOTS,
                "skill_count": len(guest_skill_records),
                "skill_books": skill_books,
                "skill_point_form": AllocateSkillPointsForm(manor=manor, initial={"guest": guest}),
                "gear_sets": gear_sets,
                "gear_set_map": gear_set_map,
            }
        )
        context["skill_point_form"].fields["guest"].queryset = manor.guests.filter(pk=guest.pk)
        return context


@login_required
@require_POST
def dismiss_guest_view(request, pk: int):
    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests, pk=pk)
    gear_items = list(guest.gear_items.select_related("template"))
    gear_summary = Counter(gear.template.name for gear in gear_items)
    if gear_items:
        from ..services import unequip_guest_item

        errors = []
        for gear in gear_items:
            try:
                unequip_guest_item(gear, guest)
            except (GameError, ValueError) as exc:
                errors.append(sanitize_error_message(exc))
    guest_name = guest.display_name
    guest.delete()
    if gear_items and errors:
        messages.warning(request, f"已辞退 {guest_name}，但部分装备未能返还：{'；'.join(errors)}")
    elif gear_items:
        readable = "、".join(
            f"{name} x{count}" if count > 1 else name for name, count in gear_summary.items()
        )
        messages.success(request, f"已辞退 {guest_name}，装备已归还仓库（{readable}）")
    else:
        messages.info(request, f"已辞退 {guest_name}。")
    return redirect("guests:roster")
