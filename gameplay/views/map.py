"""
地图和踢馆系统视图
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import json_error, json_success, parse_json_object, safe_int, safe_positive_int
from core.utils.locked_actions import (
    ActionLockSpec,
    acquire_scoped_action_lock,
    build_scoped_action_lock_key,
    execute_locked_action,
    release_scoped_action_lock,
)
from core.utils.rate_limit import rate_limit_json
from core.utils.view_error_mapping import (
    DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    LEGACY_VALUE_ERROR_VIEW_EXCEPTIONS,
    json_error_response_for_exception,
)
from gameplay.constants import REGION_CHOICES, UIConstants
from gameplay.models import Manor as ManorModel
from gameplay.models import RaidRun
from gameplay.selectors.map import get_map_context, get_raid_config_context
from gameplay.services.manor.core import get_manor
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
from gameplay.services.resources import project_resource_production_for_read
from gameplay.views.read_helpers import get_prepared_manor_for_read

MAP_ACTION_LOCK_SECONDS = 5
MAP_ACTION_LOCK_NAMESPACE = "map:view_lock"
logger = logging.getLogger(__name__)
MAP_ACTION_LOCK_SPEC = ActionLockSpec(
    namespace=MAP_ACTION_LOCK_NAMESPACE,
    timeout_seconds=MAP_ACTION_LOCK_SECONDS,
    logger=logger,
    log_context="map action lock",
)


MapActionResult = TypeVar("MapActionResult")


def _map_action_conflict_response() -> JsonResponse:
    return json_error("请求处理中，请稍候重试", status=409)


def _map_action_error_response(exc: Exception, *, log_message: str, log_args: tuple[object, ...]) -> JsonResponse:
    return cast(
        JsonResponse,
        json_error_response_for_exception(
            exc,
            log_message=log_message,
            log_args=log_args,
            logger_instance=logger,
        ),
    )


def _run_locked_map_json_action(
    request: HttpRequest,
    *,
    manor: Any,
    action_name: str,
    scope: str,
    operation: Callable[[], MapActionResult],
    success_response: Callable[[MapActionResult], JsonResponse],
    log_message: str,
    log_args: tuple[object, ...],
    known_exceptions: tuple[type[Exception], ...] = LEGACY_VALUE_ERROR_VIEW_EXCEPTIONS,
) -> JsonResponse:
    return execute_locked_action(
        action_name=action_name,
        owner_id=int(manor.id),
        scope=scope,
        acquire_lock_fn=_acquire_map_action_lock,
        release_lock_fn=_release_map_action_lock,
        operation=operation,
        on_lock_conflict=_map_action_conflict_response,
        on_success=success_response,
        known_exceptions=known_exceptions,
        on_known_error=lambda exc: cast(
            JsonResponse,
            json_error_response_for_exception(
                exc,
                logger_instance=logger,
                known_exceptions=known_exceptions,
            ),
        ),
        on_database_error=lambda exc: _map_action_error_response(exc, log_message=log_message, log_args=log_args),
        on_unexpected_error=lambda exc: _map_action_error_response(exc, log_message=log_message, log_args=log_args),
        unexpected_exceptions=DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    )


def _resolve_attack_fields_from_info(info: dict[str, Any], viewer_manor: Any, target_manor: Any) -> tuple[bool, str]:
    can_attack_value = info.get("can_attack")
    attack_reason_value = info.get("attack_reason")
    if isinstance(can_attack_value, bool) and isinstance(attack_reason_value, str):
        return can_attack_value, attack_reason_value
    return can_attack_target(viewer_manor, target_manor)


def _request_json_object_or_error(request: HttpRequest) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    data = parse_json_object(request.body)
    if data is None:
        return None, json_error("无效的请求数据")
    return data, None


def _target_manor_or_error(data: dict[str, Any]) -> tuple[ManorModel | None, JsonResponse | None]:
    target_id = safe_positive_int(data.get("target_id"), default=None)
    if target_id is None:
        return None, json_error("目标庄园参数无效")
    try:
        return ManorModel.objects.get(pk=target_id), None
    except (ManorModel.DoesNotExist, ValueError, TypeError):
        return None, json_error("目标庄园不存在", status=404)


def _request_target_manor_or_error(
    request: HttpRequest,
) -> tuple[dict[str, Any] | None, ManorModel | None, JsonResponse | None]:
    data, error = _request_json_object_or_error(request)
    if error is not None:
        return None, None, error
    if data is None:
        return None, None, json_error("无效的请求数据")
    target_manor, error = _target_manor_or_error(data)
    if error is not None:
        return None, None, error
    if target_manor is None:
        return data, None, json_error("目标庄园不存在", status=404)
    return data, target_manor, None


def _map_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return build_scoped_action_lock_key(MAP_ACTION_LOCK_SPEC, action, manor_id, scope)


def _acquire_map_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    return acquire_scoped_action_lock(MAP_ACTION_LOCK_SPEC, action, manor_id, scope)


def _release_map_action_lock(lock_key: str, lock_token: str | None) -> None:
    release_scoped_action_lock(MAP_ACTION_LOCK_SPEC, lock_key, lock_token)


def _build_raid_status_response(manor: Any) -> JsonResponse:
    active_raids = get_active_raids(manor)
    active_scouts = get_active_scouts(manor)
    incoming_raids = get_incoming_raids(manor)

    return json_success(
        active_raids=[
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
        active_scouts=[
            {
                "id": s.id,
                "target_name": s.defender.display_name,
                "time_remaining": s.time_remaining,
                "success_rate": round(s.success_rate * 100),
            }
            for s in active_scouts
        ],
        incoming_raids=[
            {
                "id": r.id,
                "attacker_name": r.attacker.display_name,
                "attacker_location": r.attacker.location_display,
                "time_remaining": r.time_remaining,
            }
            for r in incoming_raids
        ],
    )


def _refresh_raid_activity(manor: Any) -> None:
    refresh_scout_records(manor, prefer_async=True)
    refresh_raid_runs(manor, prefer_async=True)


class MapView(LoginRequiredMixin, TemplateView):
    """世界地图页面"""

    template_name = "gameplay/map.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manor = get_prepared_manor_for_read(
            self.request,
            logger=logger,
            source="map_view",
            project_fn=project_resource_production_for_read,
        )
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

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manor = get_prepared_manor_for_read(
            self.request,
            project_fn=project_resource_production_for_read,
            logger=logger,
            source="raid_config_view",
        )

        target_id = self.kwargs.get("target_id")

        # 获取目标庄园
        target_manor = get_object_or_404(ManorModel, pk=target_id)

        context.update(get_raid_config_context(manor, target_manor))

        return context


@login_required
def map_search_api(request: HttpRequest) -> JsonResponse:
    """地图搜索API（支持按名称和地区）"""
    manor = get_manor(request.user)

    search_type = request.GET.get("type", "region")
    query = request.GET.get("q", "").strip()
    region = request.GET.get("region", manor.region)
    page = safe_int(request.GET.get("page", "1"), 1, min_val=1) or 1
    page_size = UIConstants.MAP_SEARCH_PAGE_SIZE

    if search_type == "name" and query:
        # 按名称搜索
        results = search_manors_by_name(manor, query, limit=UIConstants.MAP_SEARCH_NAME_LIMIT)
        return json_success(results=results, total=len(results))
    else:
        # 按地区搜索
        results, total = search_manors_by_region(manor, region, page=page, page_size=page_size)
        return json_success(
            results=results,
            total=total,
            page=page,
            page_size=page_size,
            has_more=page * page_size < total,
        )


@login_required
def manor_detail_api(request: HttpRequest, manor_id: int) -> JsonResponse:
    """获取庄园详情API"""
    viewer_manor = get_manor(request.user)

    try:
        # 优化：使用 select_related 预加载用户信息
        target_manor = ManorModel.objects.select_related("user").get(pk=manor_id)
    except ManorModel.DoesNotExist:
        return json_error("庄园不存在", status=404)

    info = get_manor_public_info(target_manor, viewer=viewer_manor)
    can_attack, reason = _resolve_attack_fields_from_info(info, viewer_manor, target_manor)

    return json_success(manor=info, can_attack=can_attack, attack_reason=reason)


@login_required
@require_POST
@rate_limit_json("scout", limit=30, window_seconds=60, error_message="侦察过于频繁，请稍后再试")
def start_scout_api(request: HttpRequest) -> JsonResponse:
    """发起侦察API"""
    manor = get_manor(request.user)

    _data, target_manor, error = _request_target_manor_or_error(request)
    if error is not None:
        return error
    if target_manor is None:
        return json_error("目标庄园不存在", status=404)

    return _run_locked_map_json_action(
        request,
        manor=manor,
        action_name="start_scout",
        scope=str(target_manor.id),
        operation=lambda: start_scout(manor, target_manor),
        success_response=lambda record: json_success(
            message=f"已派出探子前往 {target_manor.display_name}",
            scout_id=record.id,
            travel_time=record.travel_time,
            success_rate=round(record.success_rate * 100),
        ),
        log_message="Unexpected scout start error: manor_id=%s user_id=%s target_id=%s",
        log_args=(
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            getattr(target_manor, "id", None),
        ),
        known_exceptions=(GameError,),
    )


@login_required
@require_POST
@rate_limit_json("raid", limit=20, window_seconds=60, error_message="进攻过于频繁，请稍后再试")
def start_raid_api(request: HttpRequest) -> JsonResponse:
    """发起踢馆API"""
    manor = get_manor(request.user)

    data, target_manor, error = _request_target_manor_or_error(request)
    if error is not None:
        return error
    if data is None:
        return json_error("无效的请求数据")
    if target_manor is None:
        return json_error("目标庄园不存在", status=404)

    guest_ids = data.get("guest_ids", [])
    troop_loadout = data.get("troop_loadout", {})

    if not guest_ids:
        return json_error("请选择出征门客")

    return _run_locked_map_json_action(
        request,
        manor=manor,
        action_name="start_raid",
        scope=str(target_manor.id),
        operation=lambda: start_raid(manor, target_manor, guest_ids, troop_loadout),
        success_response=lambda run: json_success(
            message=f"已向 {target_manor.display_name} 发起进攻",
            raid_id=run.id,
            travel_time=run.travel_time,
        ),
        log_message="Unexpected raid start error: manor_id=%s user_id=%s target_id=%s",
        log_args=(
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            getattr(target_manor, "id", None),
        ),
        known_exceptions=(GameError,),
    )


@login_required
@require_POST
@rate_limit_json("raid_retreat", limit=60, window_seconds=60, error_message="撤退操作过于频繁，请稍后再试")
def retreat_raid_api(request: HttpRequest, raid_id: int) -> JsonResponse:
    """撤退API"""
    manor = get_manor(request.user)

    try:
        run = RaidRun.objects.get(pk=raid_id, attacker=manor)
    except RaidRun.DoesNotExist:
        return json_error("出征记录不存在", status=404)

    return _run_locked_map_json_action(
        request,
        manor=manor,
        action_name="retreat_raid",
        scope=str(raid_id),
        operation=lambda: request_raid_retreat(run),
        success_response=lambda _result: json_success(message="已开始撤退"),
        log_message="Unexpected raid retreat error: manor_id=%s user_id=%s raid_id=%s",
        log_args=(
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            raid_id,
        ),
    )


@login_required
@require_POST
@rate_limit_json("raid_activity_refresh", limit=30, window_seconds=60, error_message="状态刷新过于频繁，请稍后再试")
def refresh_raid_activity_api(request: HttpRequest) -> JsonResponse:
    """显式触发侦察/踢馆补偿刷新。"""
    manor = get_manor(request.user)

    return _run_locked_map_json_action(
        request,
        manor=manor,
        action_name="refresh_raid_activity",
        scope="self",
        operation=lambda: _refresh_raid_activity(manor),
        success_response=lambda _result: _build_raid_status_response(manor),
        log_message="Unexpected raid activity refresh error: manor_id=%s user_id=%s",
        log_args=(
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
        ),
    )


@login_required
def raid_status_api(request: HttpRequest) -> JsonResponse:
    """获取当前出征和来袭状态API"""
    manor = get_manor(request.user)
    return _build_raid_status_response(manor)


@login_required
def protection_status_api(request: HttpRequest) -> JsonResponse:
    """获取保护状态API"""
    manor = get_manor(request.user)

    status = get_protection_status(manor)
    return json_success(protection=status)
