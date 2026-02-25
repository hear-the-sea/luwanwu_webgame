"""
门客招募视图：招募、候选处理、放大镜
"""

from __future__ import annotations

import hashlib
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import is_ajax_request, json_error, json_success, safe_positive_int, sanitize_error_message
from core.utils.cache_lock import acquire_best_effort_lock, release_best_effort_lock
from core.utils.rate_limit import rate_limit_redirect

from ..forms import RecruitForm
from ..models import RecruitmentCandidate
from ..services import (
    bulk_finalize_candidates,
    convert_candidate_to_retainer,
    start_guest_recruitment,
    use_magnifying_glass_for_candidates,
)

logger = logging.getLogger(__name__)
RECRUIT_ACTION_LOCK_SECONDS = 5
ALLOWED_CANDIDATE_ACTIONS = frozenset({"accept", "retain", "discard"})
ALLOWED_CANDIDATE_SCOPES = frozenset({"selected", "all"})
RECRUIT_SUCCESS_NAME_PREVIEW_LIMIT = 12
_LOCAL_LOCK_PREFIX = "local:"


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


def _invalidate_recruitment_hall_cache_for_manor(manor_id: int | None) -> None:
    if not manor_id:
        return
    try:
        from gameplay.services.utils.cache import invalidate_recruitment_hall_cache

        invalidate_recruitment_hall_cache(int(manor_id))
    except Exception:
        logger.debug("Failed to invalidate recruitment hall cache from view: manor_id=%s", manor_id, exc_info=True)


def _recruit_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return f"recruit:view_lock:{action}:{manor_id}:{scope}"


def _acquire_recruit_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str]:
    key = _recruit_action_lock_key(action, manor_id, scope)
    acquired, from_cache = acquire_best_effort_lock(
        key,
        timeout_seconds=RECRUIT_ACTION_LOCK_SECONDS,
        logger=logger,
        log_context="recruit action lock",
    )
    if not acquired:
        return False, ""
    if from_cache:
        return True, key
    return True, f"{_LOCAL_LOCK_PREFIX}{key}"


def _release_recruit_action_lock(lock_key: str) -> None:
    if not lock_key:
        return
    if lock_key.startswith(_LOCAL_LOCK_PREFIX):
        release_best_effort_lock(
            lock_key[len(_LOCAL_LOCK_PREFIX) :],
            from_cache=False,
            logger=logger,
            log_context="recruit action lock",
        )
        return
    release_best_effort_lock(
        lock_key,
        from_cache=True,
        logger=logger,
        log_context="recruit action lock",
    )


def _candidate_scope_digest(action: str, scope: str, candidate_ids: list[int] | None = None) -> str:
    payload = f"{action}|{scope}"
    if scope == "selected" and candidate_ids:
        normalized = ",".join(str(i) for i in sorted(set(candidate_ids)))
        payload = f"{payload}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


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


@method_decorator(require_POST, name="dispatch")
@method_decorator(rate_limit_redirect("recruit_draw", limit=10, window_seconds=60), name="dispatch")
class RecruitView(LoginRequiredMixin, TemplateView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        from gameplay.services.manor.core import ensure_manor

        manor = ensure_manor(request.user)
        form = RecruitForm(request.POST)
        if not form.is_valid():
            messages.error(request, "请选择有效的卡池")
            return redirect("gameplay:recruitment_hall")
        pool = form.cleaned_data["pool"]
        lock_ok, lock_key = _acquire_recruit_action_lock("draw", int(manor.id), str(pool.key))
        if not lock_ok:
            messages.warning(request, "请求处理中，请稍候重试")
            return redirect("gameplay:recruitment_hall")

        try:
            try:
                recruitment = start_guest_recruitment(manor, pool)
                eta_text = _format_duration(recruitment.duration_seconds)
                _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
                messages.success(request, f"{pool.name} 已开始招募，预计 {eta_text} 后完成。")
            except (GameError, ValueError) as exc:
                messages.error(request, sanitize_error_message(exc))
            except Exception as exc:
                logger.exception(
                    "Unexpected recruit draw error: manor_id=%s user_id=%s pool_key=%s",
                    getattr(manor, "id", None),
                    getattr(request.user, "id", None),
                    getattr(pool, "key", None),
                )
                messages.error(request, sanitize_error_message(exc))
        finally:
            _release_recruit_action_lock(lock_key)
        return redirect("gameplay:recruitment_hall")


@login_required
@require_POST
@rate_limit_redirect("recruit_accept", limit=10, window_seconds=60)
def accept_candidate_view(request):
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(request.user)
    scope = _normalize_candidate_scope(request.POST.get("scope"))
    if scope is None:
        messages.error(request, "选择范围无效")
        return redirect("gameplay:recruitment_hall")

    candidate_ids: list[int] | None = None
    if scope == "all":
        queryset = RecruitmentCandidate.objects.filter(manor=manor).order_by("id")
        candidates = []
    else:
        raw_candidate_ids = request.POST.getlist("candidate_ids")
        if not raw_candidate_ids:
            messages.warning(request, "请先勾选候选门客。")
            return redirect("gameplay:recruitment_hall")

        parsed_ids = _parse_positive_candidate_ids(raw_candidate_ids)
        if parsed_ids is None:
            messages.error(request, "候选门客选择有误")
            return redirect("gameplay:recruitment_hall")
        candidate_ids = parsed_ids
        queryset, candidates = _load_selected_candidates(manor, candidate_ids)

    action = _normalize_candidate_action(request.POST.get("action"))
    if action is None:
        messages.error(request, "操作类型无效")
        return redirect("gameplay:recruitment_hall")

    if scope == "all":
        if action == "discard":
            candidate_total = queryset.count()
            if candidate_total <= 0:
                messages.error(request, "当前没有可操作的候选门客。")
                return redirect("gameplay:recruitment_hall")
        else:
            candidates = list(queryset)
            if not candidates:
                messages.error(request, "当前没有可操作的候选门客。")
                return redirect("gameplay:recruitment_hall")
    elif not candidates:
        messages.error(request, "未找到选中的候选门客。")
        return redirect("gameplay:recruitment_hall")

    lock_scope = _candidate_scope_digest(action, scope, candidate_ids)
    lock_ok, lock_key = _acquire_recruit_action_lock("accept", int(manor.id), lock_scope)
    if not lock_ok:
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:recruitment_hall")

    try:
        try:
            if action == "discard":
                deleted = queryset.count() if scope == "all" else len(candidates)
                queryset.delete()
                messages.info(request, f"已放弃 {deleted} 名候选门客。")
                _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
            elif action == "retain":
                retained, error_message = _retain_candidates(candidates)
                if retained:
                    messages.success(request, f"已将 {retained} 名候选收为家丁。")
                    _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
                if error_message:
                    messages.error(request, error_message)
            else:
                # 使用批量确认函数优化性能
                succeeded, failed = _finalize_candidates(candidates)
                if succeeded:
                    messages.success(request, _format_bulk_recruit_success_message(succeeded))
                    _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
                if failed:
                    messages.warning(request, f"门客容量不足，{len(failed)} 名候选未能招募")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected recruit accept error: manor_id=%s user_id=%s action=%s candidate_count=%s",
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                action,
                len(candidates),
            )
            messages.error(request, sanitize_error_message(exc))
    finally:
        _release_recruit_action_lock(lock_key)
    return redirect("gameplay:recruitment_hall")


@login_required
@require_POST
@rate_limit_redirect("recruit_reveal", limit=10, window_seconds=60)
def use_magnifying_glass_view(request):
    """使用放大镜显现候选门客的稀有度"""
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(request.user)
    item_id = request.POST.get("item_id")

    is_ajax = is_ajax_request(request)
    item_id_int = safe_positive_int(item_id, default=None)
    if item_id_int is None:
        error_msg = "未找到放大镜道具"
        if is_ajax:
            return json_error(error_msg, status=400)
        messages.error(request, error_msg)
        return redirect("gameplay:recruitment_hall")

    lock_ok, lock_key = _acquire_recruit_action_lock("reveal", int(manor.id), str(item_id_int))
    if not lock_ok:
        if is_ajax:
            return json_error("请求处理中，请稍候重试", status=409)
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:recruitment_hall")

    try:
        try:
            count = use_magnifying_glass_for_candidates(manor, item_id_int)
            if count > 0:
                msg = f"使用放大镜成功：显现 {count} 位候选门客的稀有度"
                _invalidate_recruitment_hall_cache_for_manor(getattr(manor, "id", None))
                if is_ajax:
                    return json_success(message=msg)
                messages.success(request, msg)
            else:
                msg = "当前候选门客的稀有度已全部显现"
                if is_ajax:
                    return json_error(msg, status=400)
                messages.info(request, msg)
        except (GameError, ValueError) as exc:
            error_msg = sanitize_error_message(exc)
            if is_ajax:
                return json_error(error_msg, status=400)
            messages.error(request, error_msg)
        except Exception as exc:
            logger.exception(
                "Unexpected magnifying-glass view error: manor_id=%s user_id=%s item_id=%s",
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                item_id_int,
            )
            error_msg = sanitize_error_message(exc)
            if is_ajax:
                return json_error(error_msg, status=500)
            messages.error(request, error_msg)
    finally:
        _release_recruit_action_lock(lock_key)

    return redirect("gameplay:recruitment_hall")
