"""
门客招募视图：招募、候选处理、放大镜
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect

from ..forms import RecruitForm
from ..models import RecruitmentCandidate
from ..services import (
    bulk_finalize_candidates,
    convert_candidate_to_retainer,
    recruit_guest,
    reveal_candidate_rarity,
)


@method_decorator(require_POST, name="dispatch")
@method_decorator(rate_limit_redirect("recruit_draw", limit=10, window_seconds=60), name="dispatch")
class RecruitView(LoginRequiredMixin, TemplateView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        from gameplay.services.manor import ensure_manor

        manor = ensure_manor(request.user)
        form = RecruitForm(request.POST)
        if not form.is_valid():
            messages.error(request, "请选择有效的卡池")
            return redirect("gameplay:recruitment_hall")
        pool = form.cleaned_data["pool"]
        try:
            candidates = recruit_guest(manor, pool)
            messages.success(request, f"{pool.name} 生成 {len(candidates)} 名候选，等待挑选。")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        return redirect("gameplay:recruitment_hall")


@login_required
@require_POST
@rate_limit_redirect("recruit_accept", limit=10, window_seconds=60)
def accept_candidate_view(request):
    from gameplay.services.manor import ensure_manor

    manor = ensure_manor(request.user)
    candidate_ids = request.POST.getlist("candidate_ids")
    action = request.POST.get("action")
    if not candidate_ids:
        messages.warning(request, "请先勾选候选门客。")
        return redirect("gameplay:recruitment_hall")

    queryset = RecruitmentCandidate.objects.filter(manor=manor, id__in=candidate_ids)
    candidates = list(queryset)
    if not candidates:
        messages.error(request, "未找到选中的候选门客。")
        return redirect("gameplay:recruitment_hall")

    if action == "discard":
        deleted = len(candidates)
        queryset.delete()
        messages.info(request, f"已放弃 {deleted} 名候选门客。")
    elif action == "retain":
        retained = 0
        error_message = None
        for candidate in candidates:
            try:
                convert_candidate_to_retainer(candidate)
                retained += 1
            except (GameError, ValueError) as exc:
                error_message = sanitize_error_message(exc)
                break
        if retained:
            messages.success(request, f"已将 {retained} 名候选收为家丁。")
        if error_message:
            messages.error(request, error_message)
    else:
        # 使用批量确认函数优化性能
        try:
            succeeded, failed = bulk_finalize_candidates(candidates)
            if succeeded:
                names = [g.display_name for g in succeeded]
                messages.success(request, f"成功招募 {len(succeeded)} 名门客：{', '.join(names)}")
            if failed:
                messages.warning(request, f"门客容量不足，{len(failed)} 名候选未能招募")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:recruitment_hall")


@login_required
@require_POST
@rate_limit_redirect("recruit_reveal", limit=10, window_seconds=60)
def use_magnifying_glass_view(request):
    """使用放大镜显现候选门客的稀有度"""
    from gameplay.models import InventoryItem
    from gameplay.services.inventory import consume_inventory_item
    from gameplay.services.manor import ensure_manor

    manor = ensure_manor(request.user)
    item_id = request.POST.get("item_id")

    if not item_id:
        messages.error(request, "未找到放大镜道具")
        return redirect("gameplay:recruitment_hall")

    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=item_id,
        template__key="fangdajing",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    try:
        count = reveal_candidate_rarity(manor)
        if count > 0:
            consume_inventory_item(item)
            messages.success(request, f"使用放大镜成功：显现 {count} 位候选门客的稀有度")
        else:
            messages.info(request, "当前候选门客的稀有度已全部显现")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:recruitment_hall")
