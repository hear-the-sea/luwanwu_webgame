"""
地图和踢馆系统视图
"""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.utils import safe_int
from core.utils.rate_limit import rate_limit_json
from gameplay.constants import REGION_CHOICES, UIConstants
from gameplay.models import Manor as ManorModel
from gameplay.models import RaidRun
from gameplay.selectors.map import get_map_context, get_raid_config_context
from gameplay.services import ensure_manor, refresh_manor_state
from gameplay.services.raid import (
    get_active_raids,
    get_active_scouts,
    get_incoming_raids,
    refresh_raid_runs,
    refresh_scout_records,
    request_raid_retreat,
    search_manors_by_name,
    search_manors_by_region,
    start_raid,
    start_scout,
)
from gameplay.services.raid.map_search import get_manor_public_info
from gameplay.services.raid.protection import get_protection_status
from gameplay.services.raid.utils import can_attack_target


class MapView(LoginRequiredMixin, TemplateView):
    """世界地图页面"""

    template_name = "gameplay/map.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        # 获取当前选中的地区（默认显示玩家所在地区）
        selected_region = self.request.GET.get("region", manor.region)

        # 获取搜索查询
        search_query = self.request.GET.get("q", "").strip()

        context.update(get_map_context(manor, selected_region, search_query))
        context["regions"] = REGION_CHOICES

        return context


class RaidConfigView(LoginRequiredMixin, TemplateView):
    """踢馆出征配置页面"""

    template_name = "gameplay/raid_config.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        target_id = self.kwargs.get("target_id")

        # 获取目标庄园
        target_manor = get_object_or_404(ManorModel, pk=target_id)

        context.update(get_raid_config_context(manor, target_manor))

        return context


@login_required
def map_search_api(request: HttpRequest) -> JsonResponse:
    """地图搜索API（支持按名称和地区）"""
    manor = ensure_manor(request.user)

    search_type = request.GET.get("type", "region")
    query = request.GET.get("q", "").strip()
    region = request.GET.get("region", manor.region)
    page = safe_int(request.GET.get("page", "1"), 1)
    page_size = UIConstants.MAP_SEARCH_PAGE_SIZE

    if search_type == "name" and query:
        # 按名称搜索
        results = search_manors_by_name(manor, query, limit=UIConstants.MAP_SEARCH_NAME_LIMIT)
        return JsonResponse(
            {
                "success": True,
                "results": results,
                "total": len(results),
            }
        )
    else:
        # 按地区搜索
        results, total = search_manors_by_region(manor, region, page=page, page_size=page_size)
        return JsonResponse(
            {
                "success": True,
                "results": results,
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": page * page_size < total,
            }
        )


@login_required
def manor_detail_api(request: HttpRequest, manor_id: int) -> JsonResponse:
    """获取庄园详情API"""
    viewer_manor = ensure_manor(request.user)

    try:
        # 优化：使用 select_related 预加载用户信息
        target_manor = ManorModel.objects.select_related("user").get(pk=manor_id)
    except ManorModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "庄园不存在"}, status=404)

    info = get_manor_public_info(target_manor, viewer=viewer_manor)
    can_attack, reason = can_attack_target(viewer_manor, target_manor)

    return JsonResponse(
        {
            "success": True,
            "manor": info,
            "can_attack": can_attack,
            "attack_reason": reason,
        }
    )


@login_required
@require_POST
@rate_limit_json("scout", limit=30, window_seconds=60, error_message="侦察过于频繁，请稍后再试")
def start_scout_api(request: HttpRequest) -> JsonResponse:
    """发起侦察API"""
    manor = ensure_manor(request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "无效的请求数据"}, status=400)

    target_id = data.get("target_id")
    if not target_id:
        return JsonResponse({"success": False, "error": "请指定目标庄园"}, status=400)

    try:
        target_manor = ManorModel.objects.get(pk=target_id)
    except ManorModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "目标庄园不存在"}, status=404)

    try:
        record = start_scout(manor, target_manor)
        return JsonResponse(
            {
                "success": True,
                "message": f"已派出探子前往 {target_manor.display_name}",
                "scout_id": record.id,
                "travel_time": record.travel_time,
                "success_rate": round(record.success_rate * 100),
            }
        )
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@require_POST
@rate_limit_json("raid", limit=20, window_seconds=60, error_message="进攻过于频繁，请稍后再试")
def start_raid_api(request: HttpRequest) -> JsonResponse:
    """发起踢馆API"""
    manor = ensure_manor(request.user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "无效的请求数据"}, status=400)

    target_id = data.get("target_id")
    guest_ids = data.get("guest_ids", [])
    troop_loadout = data.get("troop_loadout", {})

    if not target_id:
        return JsonResponse({"success": False, "error": "请指定目标庄园"}, status=400)
    if not guest_ids:
        return JsonResponse({"success": False, "error": "请选择出征门客"}, status=400)

    try:
        target_manor = ManorModel.objects.get(pk=target_id)
    except ManorModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "目标庄园不存在"}, status=404)

    try:
        run = start_raid(manor, target_manor, guest_ids, troop_loadout)
        return JsonResponse(
            {
                "success": True,
                "message": f"已向 {target_manor.display_name} 发起进攻",
                "raid_id": run.id,
                "travel_time": run.travel_time,
            }
        )
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@require_POST
@rate_limit_json("raid_retreat", limit=60, window_seconds=60, error_message="撤退操作过于频繁，请稍后再试")
def retreat_raid_api(request: HttpRequest, raid_id: int) -> JsonResponse:
    """撤退API"""
    manor = ensure_manor(request.user)

    try:
        run = RaidRun.objects.get(pk=raid_id, attacker=manor)
    except RaidRun.DoesNotExist:
        return JsonResponse({"success": False, "error": "出征记录不存在"}, status=404)

    try:
        request_raid_retreat(run)
        return JsonResponse(
            {
                "success": True,
                "message": "已开始撤退",
            }
        )
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
def raid_status_api(request: HttpRequest) -> JsonResponse:
    """获取当前出征和来袭状态API"""
    manor = ensure_manor(request.user)

    # 刷新状态
    refresh_raid_runs(manor)
    refresh_scout_records(manor)

    active_raids = get_active_raids(manor)
    active_scouts = get_active_scouts(manor)
    incoming_raids = get_incoming_raids(manor)

    return JsonResponse(
        {
            "success": True,
            "active_raids": [
                {
                    "id": r.id,
                    "target_name": r.defender.display_name,
                    "status": r.status,
                    "status_display": r.get_status_display(),
                    "time_remaining": r.time_remaining,
                    "can_retreat": r.can_retreat,
                }
                for r in active_raids
            ],
            "active_scouts": [
                {
                    "id": s.id,
                    "target_name": s.defender.display_name,
                    "time_remaining": s.time_remaining,
                    "success_rate": round(s.success_rate * 100),
                }
                for s in active_scouts
            ],
            "incoming_raids": [
                {
                    "id": r.id,
                    "attacker_name": r.attacker.display_name,
                    "attacker_location": r.attacker.location_display,
                    "time_remaining": r.time_remaining,
                }
                for r in incoming_raids
            ],
        }
    )


@login_required
def protection_status_api(request: HttpRequest) -> JsonResponse:
    """获取保护状态API"""
    manor = ensure_manor(request.user)

    status = get_protection_status(manor)
    return JsonResponse(
        {
            "success": True,
            "protection": status,
        }
    )
