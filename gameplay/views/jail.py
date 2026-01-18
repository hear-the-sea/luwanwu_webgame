"""
监牢与结义林 API 视图
"""

from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.utils import safe_int
from core.utils.rate_limit import rate_limit_json
from core.utils.validation import sanitize_error_message

from gameplay.constants import PVPConstants
from gameplay.services import (
    add_oath_bond,
    draw_pie,
    ensure_manor,
    list_held_prisoners,
    list_oath_bonds,
    release_prisoner,
    recruit_prisoner,
    remove_oath_bond,
)


class JailView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/jail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        prisoners = list_held_prisoners(manor)
        context.update(
            {
                "manor": manor,
                "jail_capacity": int(getattr(manor, "jail_capacity", 0) or 0),
                "prisoners": prisoners,
                "capture_rate_percent": int(round(float(PVPConstants.RAID_CAPTURE_GUEST_RATE) * 100)),
                "recruit_loyalty_threshold": int(PVPConstants.JAIL_RECRUIT_LOYALTY_THRESHOLD),
                "recruit_cost_gold_bar": int(PVPConstants.JAIL_RECRUIT_GOLD_BAR_COST),
            }
        )
        return context


class OathGroveView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/oath_grove.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        bonds = list_oath_bonds(manor)
        oathed_ids = {b.guest_id for b in bonds}
        available_guests = (
            manor.guests.select_related("template")
            .exclude(id__in=oathed_ids)
            .order_by("-template__rarity", "-level", "id")
        )
        context.update(
            {
                "manor": manor,
                "oath_capacity": int(getattr(manor, "oath_capacity", 0) or 0),
                "bonds": bonds,
                "available_guests": list(available_guests)[:50],
            }
        )
        return context


@login_required
def jail_status_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
    prisoners = list_held_prisoners(manor)
    return JsonResponse(
        {
            "success": True,
            "jail": {
                "capacity": int(getattr(manor, "jail_capacity", 0) or 0),
                "count": len(prisoners),
                "prisoners": [
                    {
                        "id": p.id,
                        "name": p.display_name,
                        "template_key": getattr(p.guest_template, "key", ""),
                        "rarity": getattr(p.guest_template, "rarity", ""),
                        "loyalty": int(p.loyalty),
                        "captured_at": p.captured_at.isoformat() if p.captured_at else "",
                        "original_manor": getattr(getattr(p, "original_manor", None), "display_name", ""),
                    }
                    for p in prisoners
                ],
            },
        }
    )


@login_required
def oath_status_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
    bonds = list_oath_bonds(manor)
    return JsonResponse(
        {
            "success": True,
            "oath_grove": {
                "capacity": int(getattr(manor, "oath_capacity", 0) or 0),
                "count": len(bonds),
                "bonds": [
                    {
                        "guest_id": b.guest_id,
                        "name": b.guest.display_name,
                        "template_key": getattr(b.guest.template, "key", ""),
                        "rarity": getattr(b.guest.template, "rarity", ""),
                        "created_at": b.created_at.isoformat() if b.created_at else "",
                    }
                    for b in bonds
                ],
            },
        }
    )


@login_required
@require_POST
def recruit_prisoner_view(request: HttpRequest, prisoner_id: int):
    manor = ensure_manor(request.user)
    try:
        guest = recruit_prisoner(manor, int(prisoner_id))
        messages.success(request, f"成功招募：{guest.display_name}（等级已重置，装备已清空）")
    except Exception as exc:
        messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:jail")


@login_required
@require_POST
def draw_pie_view(request: HttpRequest, prisoner_id: int):
    manor = ensure_manor(request.user)
    try:
        prisoner = draw_pie(manor, int(prisoner_id))
        reduction = 0
        if hasattr(prisoner, "_reduction"):
            reduction = prisoner._reduction
        messages.success(request, f"画饼成功！{prisoner.display_name} 忠诚度 -{reduction}")
    except Exception as exc:
        messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:jail")


@login_required
@require_POST
def release_prisoner_view(request: HttpRequest, prisoner_id: int):
    manor = ensure_manor(request.user)
    try:
        prisoner = release_prisoner(manor, int(prisoner_id))
        messages.success(request, f"已释放：{prisoner.display_name}")
    except Exception as exc:
        messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:jail")


@login_required
@require_POST
def add_oath_bond_view(request: HttpRequest):
    manor = ensure_manor(request.user)
    guest_id = safe_int(request.POST.get("guest_id"))
    if not guest_id:
        messages.error(request, "请指定门客")
        return redirect("gameplay:oath_grove")
    try:
        bond = add_oath_bond(manor, guest_id)
        messages.success(request, f"结义成功：{bond.guest.display_name}")
    except Exception as exc:
        messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:oath_grove")


@login_required
@require_POST
def remove_oath_bond_view(request: HttpRequest, guest_id: int):
    manor = ensure_manor(request.user)
    try:
        deleted = remove_oath_bond(manor, int(guest_id))
        if not deleted:
            messages.error(request, "该门客未结义")
        else:
            messages.success(request, "已解除结义")
    except Exception as exc:
        messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:oath_grove")


@login_required
@require_POST
@rate_limit_json("jail_recruit", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def recruit_prisoner_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = ensure_manor(request.user)
    try:
        guest = recruit_prisoner(manor, int(prisoner_id))
        return JsonResponse(
            {
                "success": True,
                "message": f"成功招募：{guest.display_name}（等级已重置，装备已清空）",
                "guest_id": guest.id,
            }
        )
    except Exception as exc:
        return JsonResponse({"success": False, "error": sanitize_error_message(exc)}, status=400)


@login_required
@require_POST
@rate_limit_json("jail_draw_pie", limit=30, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def draw_pie_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = ensure_manor(request.user)
    try:
        prisoner = draw_pie(manor, int(prisoner_id))
        reduction = getattr(prisoner, "_reduction", 0)
        return JsonResponse(
            {
                "success": True,
                "message": f"画饼成功！{prisoner.display_name} 忠诚度 -{reduction}",
                "prisoner_id": prisoner.id,
                "new_loyalty": prisoner.loyalty,
                "reduction": reduction,
            }
        )
    except Exception as exc:
        return JsonResponse({"success": False, "error": sanitize_error_message(exc)}, status=400)


@login_required
@require_POST
@rate_limit_json("jail_release", limit=20, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def release_prisoner_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = ensure_manor(request.user)
    try:
        prisoner = release_prisoner(manor, int(prisoner_id))
        return JsonResponse(
            {
                "success": True,
                "message": f"已释放：{prisoner.display_name}",
                "prisoner_id": prisoner.id,
            }
        )
    except Exception as exc:
        return JsonResponse({"success": False, "error": sanitize_error_message(exc)}, status=400)


@login_required
@require_POST
@rate_limit_json("oath_add", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def add_oath_bond_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "无效的请求数据"}, status=400)

    guest_id = safe_int(data.get("guest_id"))
    if not guest_id:
        return JsonResponse({"success": False, "error": "请指定门客"}, status=400)

    try:
        bond = add_oath_bond(manor, guest_id)
        return JsonResponse(
            {
                "success": True,
                "message": f"结义成功：{bond.guest.display_name}",
            }
        )
    except Exception as exc:
        return JsonResponse({"success": False, "error": sanitize_error_message(exc)}, status=400)


@login_required
@require_POST
@rate_limit_json("oath_remove", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def remove_oath_bond_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "无效的请求数据"}, status=400)

    guest_id = safe_int(data.get("guest_id"))
    if not guest_id:
        return JsonResponse({"success": False, "error": "请指定门客"}, status=400)

    try:
        deleted = remove_oath_bond(manor, guest_id)
        if not deleted:
            return JsonResponse({"success": False, "error": "该门客未结义"}, status=400)
        return JsonResponse({"success": True, "message": "已解除结义"})
    except Exception as exc:
        return JsonResponse({"success": False, "error": sanitize_error_message(exc)}, status=400)
