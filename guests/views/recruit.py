"""
门客招募视图：招募、候选处理、放大镜
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import is_json_request, json_error, json_success, safe_positive_int, sanitize_error_message
from core.utils.locked_actions import (
    ActionLockSpec,
    acquire_scoped_action_lock,
    build_scoped_action_lock_key,
    execute_locked_action,
    release_scoped_action_lock,
)
from core.utils.rate_limit import rate_limit_redirect
from gameplay.services.resources import project_resource_production_for_read

from ..forms import RecruitForm
from ..models import RecruitmentCandidate
from ..services.recruitment import start_guest_recruitment, use_magnifying_glass_for_candidates
from ..services.recruitment_guests import bulk_finalize_candidates, convert_candidate_to_retainer
from .common import unexpected_action_error_response
from .recruit_runtime import (
    CandidateActionOutcome,
    CandidateSelection,
    RecruitViewResolutionError,
    execute_candidate_action,
    resolve_all_candidate_selection,
    resolve_selected_candidate_selection,
    reveal_candidate_rarities,
)

logger = logging.getLogger(__name__)
RECRUIT_ACTION_LOCK_SECONDS = 5
ALLOWED_CANDIDATE_ACTIONS = frozenset({"accept", "retain", "discard"})
ALLOWED_CANDIDATE_SCOPES = frozenset({"selected", "all"})
RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT = 12
RECRUIT_ACTION_LOCK_NAMESPACE = "recruit:view_lock"
RECRUIT_ACTION_LOCK_SPEC = ActionLockSpec(
    namespace=RECRUIT_ACTION_LOCK_NAMESPACE,
    timeout_seconds=RECRUIT_ACTION_LOCK_SECONDS,
    logger=logger,
    log_context="recruit action lock",
)


def _load_selected_candidates(manor, candidate_ids):
    queryset = RecruitmentCandidate.objects.filter(manor=manor, id__in=candidate_ids)
    return queryset, list(queryset)


def _parse_positive_candidate_ids(raw_values: list[str]) -> list[int] | None:
    parsed: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        value = safe_positive_int(raw, default=None)
        if value is None:
            return None
        if value in seen:
            continue
        parsed.append(value)
        seen.add(value)
    return parsed


def _retain_candidates(candidates) -> tuple[int, str | None]:
    retained = 0
    error_message = None
    for candidate in candidates:
        try:
            convert_candidate_to_retainer(candidate)
            retained += 1
        except (GameError, ValueError) as exc:
            error_message = sanitize_error_message(exc)
            break
    return retained, error_message


def _finalize_candidates(candidates) -> tuple[list, list]:
    return bulk_finalize_candidates(candidates)


def _invalidate_recruitment_hall_cache_for_manor(manor_id: int | None) -> bool:
    if not manor_id:
        return True
    try:
        from gameplay.services.utils.cache import invalidate_recruitment_hall_cache

        invalidate_recruitment_hall_cache(int(manor_id))
        return True
    except Exception:
        logger.warning("Failed to invalidate recruitment hall cache from view: manor_id=%s", manor_id, exc_info=True)
        return False


def _recruit_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return build_scoped_action_lock_key(RECRUIT_ACTION_LOCK_SPEC, action, manor_id, scope)


def _acquire_recruit_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    return acquire_scoped_action_lock(RECRUIT_ACTION_LOCK_SPEC, action, manor_id, scope)


def _release_recruit_action_lock(lock_key: str, lock_token: str | None) -> None:
    release_scoped_action_lock(RECRUIT_ACTION_LOCK_SPEC, lock_key, lock_token)


def _candidate_action_lock_scope(manor_id: int) -> str:
    return f"candidate-actions:{int(manor_id)}"


def _recruit_action_lock_conflict_response(request, manor, *, is_ajax: bool) -> HttpResponse:
    return _recruitment_hall_response(
        request,
        manor,
        "请求处理中，请稍候重试",
        is_ajax=is_ajax,
        status=409,
        message_level="warning",
    )


def _run_locked_recruit_action(
    *,
    request,
    manor,
    is_ajax: bool,
    lock_action: str,
    lock_scope: str,
    operation: Callable[[], HttpResponse],
    database_log_message: str,
    unexpected_log_message: str,
    log_args: tuple[object, ...],
) -> HttpResponse:
    return execute_locked_action(
        action_name=lock_action,
        owner_id=int(manor.id),
        scope=lock_scope,
        acquire_lock_fn=_acquire_recruit_action_lock,
        release_lock_fn=_release_recruit_action_lock,
        operation=operation,
        on_lock_conflict=lambda: _recruit_action_lock_conflict_response(request, manor, is_ajax=is_ajax),
        on_success=lambda response: response,
        known_exceptions=(GameError, ValueError),
        on_known_error=lambda exc: _recruitment_hall_response(
            request,
            manor,
            sanitize_error_message(exc),
            is_ajax=is_ajax,
            status=400,
            message_level="error",
        ),
        on_database_error=lambda exc: (
            logger.exception(database_log_message, *log_args),
            _recruitment_hall_response(
                request,
                manor,
                sanitize_error_message(exc),
                is_ajax=is_ajax,
                status=500,
                message_level="error",
            ),
        )[1],
        on_unexpected_error=lambda exc: (
            logger.exception(unexpected_log_message, *log_args),
            unexpected_action_error_response(
                request,
                exc,
                is_ajax=is_ajax,
                redirect_to="gameplay:recruitment_hall",
            ),
        )[1],
        unexpected_exceptions=(Exception,),
    )


def _normalize_candidate_action(raw_action: str | None) -> str | None:
    if raw_action in (None, ""):
        return "accept"
    if raw_action in ALLOWED_CANDIDATE_ACTIONS:
        return raw_action
    return None


def _normalize_candidate_scope(raw_scope: str | None) -> str | None:
    if raw_scope in (None, "", "selected"):
        return "selected"
    if raw_scope in ALLOWED_CANDIDATE_SCOPES:
        return raw_scope
    return None


def _format_duration(seconds: int) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if sec or not parts:
        parts.append(f"{sec}秒")
    return "".join(parts)


def _format_bulk_recruit_success_message(succeeded_guests: list) -> str:
    total = len(succeeded_guests)
    if total <= 0:
        return ""

    preview_names = [guest.display_name for guest in succeeded_guests[:RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT]]
    preview = ", ".join(preview_names)
    if total > RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT:
        remaining = total - RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT
        return f"成功招募 {total} 名门客：{preview} 等 {remaining} 名"
    return f"成功招募 {total} 名门客：{preview}"


def _build_recruitment_hall_ajax_payload(request, manor, *, use_cache: bool = True) -> dict:
    from django.template.loader import render_to_string

    from gameplay.constants import UIConstants
    from gameplay.selectors.recruitment import get_recruitment_hall_context

    project_resource_production_for_read(manor)
    context = get_recruitment_hall_context(manor, UIConstants.RECRUIT_RECORDS_DISPLAY, use_cache=use_cache)
    return {
        "hall_pools_html": render_to_string(
            "gameplay/partials/recruitment_pools_section.html", context, request=request
        ),
        "hall_candidates_html": render_to_string(
            "gameplay/partials/recruitment_candidates_section.html", context, request=request
        ),
        "hall_records_html": render_to_string(
            "gameplay/partials/recruitment_records_section.html", context, request=request
        ),
        "candidate_count": context.get("candidate_count", 0),
    }


def _json_recruitment_hall_success(
    request,
    manor,
    message: str,
    *,
    message_level: str = "success",
    use_cache: bool = True,
):
    return json_success(
        message=message,
        message_level=message_level,
        **_build_recruitment_hall_ajax_payload(request, manor, use_cache=use_cache),
    )


def _recruitment_hall_response(
    request,
    manor,
    message: str,
    *,
    is_ajax: bool,
    status: int = 200,
    message_level: str = "success",
    use_cache: bool = True,
):
    if is_ajax:
        if status >= 400:
            return json_error(message, status=status)
        return _json_recruitment_hall_success(
            request,
            manor,
            message,
            message_level=message_level,
            use_cache=use_cache,
        )

    getattr(messages, message_level)(request, message)
    return redirect("gameplay:recruitment_hall")


def _recruitment_hall_resolution_error_response(
    request,
    manor,
    resolution_error: RecruitViewResolutionError,
    *,
    is_ajax: bool,
):
    return _recruitment_hall_response(
        request,
        manor,
        resolution_error.message,
        is_ajax=is_ajax,
        status=resolution_error.status,
        message_level=resolution_error.message_level,
    )


def _candidate_action_success_response(
    request,
    manor,
    outcome: CandidateActionOutcome,
    *,
    is_ajax: bool,
):
    manor_id = getattr(manor, "id", None)

    if outcome.action == "discard":
        message = f"已放弃 {outcome.affected_count} 名候选门客。"
        cache_ok = _invalidate_recruitment_hall_cache_for_manor(manor_id)
        return _recruitment_hall_response(
            request,
            manor,
            message,
            is_ajax=is_ajax,
            message_level="warning" if is_ajax else "info",
            use_cache=cache_ok,
        )

    if outcome.action == "retain":
        if outcome.affected_count:
            cache_ok = _invalidate_recruitment_hall_cache_for_manor(manor_id)
            success_message = f"已将 {outcome.affected_count} 名候选收为家丁。"
            if is_ajax:
                message = success_message
                if outcome.error_message:
                    message = f"{message} {outcome.error_message}"
                return _recruitment_hall_response(
                    request,
                    manor,
                    message,
                    is_ajax=is_ajax,
                    use_cache=cache_ok,
                )
            messages.success(request, success_message)
            if outcome.error_message:
                messages.error(request, outcome.error_message)
            return redirect("gameplay:recruitment_hall")
        if outcome.error_message:
            return _recruitment_hall_response(
                request,
                manor,
                outcome.error_message,
                is_ajax=is_ajax,
                status=400,
            )
        return _recruitment_hall_response(
            request,
            manor,
            "当前没有可操作的候选门客。",
            is_ajax=is_ajax,
            status=400,
        )

    if outcome.succeeded:
        cache_ok = _invalidate_recruitment_hall_cache_for_manor(manor_id)
        success_message = _format_bulk_recruit_success_message(outcome.succeeded)
        if is_ajax:
            message = success_message
            if outcome.failed:
                message = f"{message}；门客容量不足，{len(outcome.failed)} 名候选未能招募"
            return _recruitment_hall_response(
                request,
                manor,
                message,
                is_ajax=is_ajax,
                use_cache=cache_ok,
            )
        messages.success(request, success_message)
        if outcome.failed:
            messages.warning(request, f"门客容量不足，{len(outcome.failed)} 名候选未能招募")
        return redirect("gameplay:recruitment_hall")

    if outcome.failed:
        cache_ok = _invalidate_recruitment_hall_cache_for_manor(manor_id)
        return _recruitment_hall_response(
            request,
            manor,
            f"门客容量不足，{len(outcome.failed)} 名候选未能招募",
            is_ajax=is_ajax,
            status=200,
            message_level="warning",
            use_cache=cache_ok,
        )

    return _recruitment_hall_response(
        request,
        manor,
        "当前没有可操作的候选门客。",
        is_ajax=is_ajax,
        status=400,
    )


@method_decorator(require_POST, name="dispatch")
@method_decorator(rate_limit_redirect("recruit_draw", limit=10, window_seconds=60), name="dispatch")
class RecruitView(LoginRequiredMixin, TemplateView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        from gameplay.services.manor.core import get_manor

        manor = get_manor(request.user)
        is_ajax = is_json_request(request)
        form = RecruitForm(request.POST)
        if not form.is_valid():
            if is_ajax:
                return json_error("请选择有效的卡池", status=400)
            messages.error(request, "请选择有效的卡池")
            return redirect("gameplay:recruitment_hall")
        pool = form.cleaned_data["pool"]

        def _perform_draw() -> HttpResponse:
            recruitment = start_guest_recruitment(manor, pool)
            eta_text = _format_duration(recruitment.duration_seconds)
            cache_ok = _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
            message = f"{pool.name} 已开始招募，预计 {eta_text} 后完成。"
            if is_ajax:
                return _json_recruitment_hall_success(request, manor, message, use_cache=cache_ok)
            messages.success(request, message)
            return redirect("gameplay:recruitment_hall")

        return _run_locked_recruit_action(
            request=request,
            manor=manor,
            is_ajax=is_ajax,
            lock_action="draw",
            lock_scope=str(pool.key),
            operation=_perform_draw,
            database_log_message="Unexpected recruit draw database error: manor_id=%s user_id=%s pool_key=%s",
            unexpected_log_message="Unexpected recruit draw error: manor_id=%s user_id=%s pool_key=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                getattr(pool, "key", None),
            ),
        )


@login_required
@require_POST
@rate_limit_redirect("recruit_accept", limit=10, window_seconds=60)
def accept_candidate_view(request):
    from gameplay.services.manor.core import get_manor

    manor = get_manor(request.user)
    is_ajax = is_json_request(request)
    scope = _normalize_candidate_scope(request.POST.get("scope"))
    if scope is None:
        return _recruitment_hall_response(request, manor, "选择范围无效", is_ajax=is_ajax, status=400)

    raw_candidate_ids = request.POST.getlist("candidate_ids")
    selection: CandidateSelection | None = None
    if scope == "selected":
        selection, resolution_error = resolve_selected_candidate_selection(
            manor=manor,
            raw_candidate_ids=raw_candidate_ids,
            parse_positive_candidate_ids=_parse_positive_candidate_ids,
            load_selected_candidates=_load_selected_candidates,
        )
        if resolution_error is not None:
            return _recruitment_hall_resolution_error_response(request, manor, resolution_error, is_ajax=is_ajax)
        assert selection is not None

    action = _normalize_candidate_action(request.POST.get("action"))
    if action is None:
        return _recruitment_hall_response(request, manor, "操作类型无效", is_ajax=is_ajax, status=400)

    if scope == "all":
        selection, resolution_error = resolve_all_candidate_selection(
            manor=manor,
            action=action,
            candidate_model=RecruitmentCandidate,
        )
        if resolution_error is not None:
            return _recruitment_hall_resolution_error_response(request, manor, resolution_error, is_ajax=is_ajax)
        assert selection is not None

    lock_scope = _candidate_action_lock_scope(int(manor.id))

    def _perform_accept() -> HttpResponse:
        assert selection is not None
        outcome = execute_candidate_action(
            action=action,
            selection=selection,
            retain_candidates=_retain_candidates,
            finalize_candidates=_finalize_candidates,
        )
        return _candidate_action_success_response(request, manor, outcome, is_ajax=is_ajax)

    return _run_locked_recruit_action(
        request=request,
        manor=manor,
        is_ajax=is_ajax,
        lock_action="candidate_action",
        lock_scope=lock_scope,
        operation=_perform_accept,
        database_log_message="Unexpected recruit accept database error: manor_id=%s user_id=%s action=%s candidate_count=%s",
        unexpected_log_message="Unexpected recruit accept error: manor_id=%s user_id=%s action=%s candidate_count=%s",
        log_args=(
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            action,
            selection.target_count,
        ),
    )


@login_required
@require_POST
@rate_limit_redirect("recruit_reveal", limit=10, window_seconds=60)
def use_magnifying_glass_view(request):
    """使用放大镜显现候选门客的稀有度"""
    from gameplay.services.manor.core import get_manor

    manor = get_manor(request.user)
    item_id = request.POST.get("item_id")

    is_ajax = is_json_request(request)
    item_id_int = safe_positive_int(item_id, default=None)
    if item_id_int is None:
        return _recruitment_hall_response(request, manor, "未找到放大镜道具", is_ajax=is_ajax, status=400)

    def _perform_reveal() -> HttpResponse:
        count = reveal_candidate_rarities(
            manor=manor,
            item_id=item_id_int,
            use_magnifying_glass_for_candidates=use_magnifying_glass_for_candidates,
        )
        if count > 0:
            cache_ok = _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
            return _recruitment_hall_response(
                request,
                manor,
                f"使用放大镜成功：显现 {count} 位候选门客的稀有度",
                is_ajax=is_ajax,
                use_cache=cache_ok,
            )
        return _recruitment_hall_response(
            request,
            manor,
            "当前候选门客的稀有度已全部显现",
            is_ajax=is_ajax,
            status=400,
            message_level="info",
        )

    return _run_locked_recruit_action(
        request=request,
        manor=manor,
        is_ajax=is_ajax,
        lock_action="reveal",
        lock_scope=str(item_id_int),
        operation=_perform_reveal,
        database_log_message="Unexpected magnifying-glass database error: manor_id=%s user_id=%s item_id=%s",
        unexpected_log_message="Unexpected magnifying-glass error: manor_id=%s user_id=%s item_id=%s",
        log_args=(
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            item_id_int,
        ),
    )
