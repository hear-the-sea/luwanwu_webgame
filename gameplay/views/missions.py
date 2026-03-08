"""
任务系统视图：任务面板、出征、撤退
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_int, sanitize_error_message
from core.utils.cache_lock import acquire_best_effort_lock, release_best_effort_lock
from gameplay.constants import UIConstants
from gameplay.models import MissionRun, MissionTemplate, ResourceType
from gameplay.services import (
    add_mission_extra_attempt,
    bulk_get_mission_extra_attempts,
    bulk_mission_attempts_today,
    ensure_manor,
    get_item_quantity,
    launch_mission,
    normalize_mission_loadout,
    refresh_manor_state,
    refresh_mission_runs,
    request_retreat,
)
from gameplay.services.recruitment.recruitment import get_player_troops
from guests.models import Guest, GuestStatus, GuestTemplate, SkillBook

# 任务卡道具 key
MISSION_CARD_KEY = "mission_card"
MISSION_ACTION_LOCK_SECONDS = 5
_LOCAL_LOCK_PREFIX = "local:"
logger = logging.getLogger(__name__)


def _handle_unexpected_mission_error(
    request: HttpRequest,
    exc: Exception,
    *,
    log_message: str,
    log_args: tuple[object, ...],
) -> None:
    flash_unexpected_view_error(
        request,
        exc,
        log_message=log_message,
        log_args=log_args,
        logger_instance=logger,
    )


def _handle_known_mission_error(request: HttpRequest, exc: GameError | ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


def _normalize_mission_key(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    mission_key = str(raw_value).strip()
    return mission_key or None


def _mission_tasks_url(mission_key: str | None = None) -> str:
    base_url = reverse("gameplay:tasks")
    if mission_key:
        return f"{base_url}?mission={mission_key}"
    return base_url


def _mission_tasks_redirect(mission_key: str | None = None) -> HttpResponse:
    return redirect(_mission_tasks_url(mission_key))


def _resolve_mission_or_redirect(
    request: HttpRequest, mission_key_raw: Any
) -> tuple[MissionTemplate | None, HttpResponse | None]:
    mission_key = _normalize_mission_key(mission_key_raw)
    if mission_key is None:
        messages.error(request, "请选择任务")
        return None, _mission_tasks_redirect()

    mission = MissionTemplate.objects.filter(key=mission_key).first()
    if mission is None:
        messages.error(request, "任务不存在")
        return None, _mission_tasks_redirect(mission_key)

    return mission, None


def _parse_positive_ids(raw_values: list[str]) -> list[int] | None:
    if not raw_values:
        return []

    parsed: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        value = safe_int(raw, default=None)
        if value is None or value <= 0:
            return None
        if value in seen:
            continue
        parsed.append(value)
        seen.add(value)
    return parsed


def _mission_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return f"mission:view_lock:{action}:{manor_id}:{scope}"


def _acquire_mission_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    key = _mission_action_lock_key(action, manor_id, scope)
    acquired, from_cache, lock_token = acquire_best_effort_lock(
        key,
        timeout_seconds=MISSION_ACTION_LOCK_SECONDS,
        logger=logger,
        log_context="mission action lock",
    )
    if not acquired:
        return False, "", None
    if from_cache:
        return True, key, lock_token
    return True, f"{_LOCAL_LOCK_PREFIX}{key}", lock_token


def _release_mission_action_lock(lock_key: str, lock_token: str | None) -> None:
    if not lock_key:
        return
    if lock_key.startswith(_LOCAL_LOCK_PREFIX):
        release_best_effort_lock(
            lock_key[len(_LOCAL_LOCK_PREFIX) :],
            from_cache=False,
            lock_token=lock_token,
            logger=logger,
            log_context="mission action lock",
        )
        return
    release_best_effort_lock(
        lock_key,
        from_cache=True,
        lock_token=lock_token,
        logger=logger,
        log_context="mission action lock",
    )


def _collect_mission_asset_keys(missions: list[MissionTemplate]) -> tuple[set[str], set[str], set[str]]:
    enemy_keys: set[str] = set()
    troop_keys: set[str] = set()
    drop_keys: set[str] = set()

    for mission in missions:
        for entry in mission.enemy_guests or []:
            if isinstance(entry, str):
                enemy_keys.add(entry)
            elif isinstance(entry, dict):
                key = entry.get("key")
                if key:
                    enemy_keys.add(key)
        troop_keys.update((mission.enemy_troops or {}).keys())
        drop_keys.update((mission.drop_table or {}).keys())

    return enemy_keys, troop_keys, drop_keys


def _parse_drop_value(value: Any) -> tuple[float | None, int | None]:
    chance = None
    count = None
    if isinstance(value, dict):
        raw_chance = value.get("chance", value.get("probability"))
        raw_count = value.get("count", value.get("quantity", value.get("amount")))
        try:
            chance = float(raw_chance) if raw_chance is not None else None
        except (TypeError, ValueError):
            chance = None
        try:
            count = int(raw_count) if raw_count is not None else None
        except (TypeError, ValueError):
            count = None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = None
        if number is not None and 0 < number < 1:
            chance = number
            count = 1
        elif number is not None and number >= 1:
            count = int(number)

    if chance is not None and count is None:
        count = 1
    return chance, count


def _resolve_drop_label(
    key: str,
    drop_labels: dict[str, str],
    item_templates: dict[str, Any],
    book_labels: dict[str, str],
) -> str:
    label = drop_labels.get(key, key)
    if label != key:
        return label
    tpl = item_templates.get(key)
    if tpl:
        return tpl.name
    if key in book_labels:
        return book_labels[key]
    return key


def _build_drop_lists(
    selected_mission: MissionTemplate,
    drop_labels: dict[str, str],
    item_templates: dict[str, Any],
    book_labels: dict[str, str],
    loot_rarities: dict[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    guaranteed_drops: list[dict[str, str]] = []
    probability_drops: list[dict[str, str]] = []

    for key, val in (selected_mission.drop_table or {}).items():
        label = _resolve_drop_label(key, drop_labels, item_templates, book_labels)
        chance, count = _parse_drop_value(val)
        rarity = loot_rarities.get(key) or "default"

        display_label = f"{label} x{count}" if (count is not None and count >= 1) else label
        if chance is not None and 0 < chance < 1:
            probability_drops.append({"label": display_label, "rarity": rarity})
        else:
            guaranteed_drops.append({"label": display_label, "rarity": rarity})

    for key, val in (selected_mission.probability_drop_table or {}).items():
        label = _resolve_drop_label(key, drop_labels, item_templates, book_labels)
        _, count = _parse_drop_value(val)
        display_label = f"{label} x{count}" if (count is not None and count >= 1) else label
        rarity = loot_rarities.get(key) or "default"
        probability_drops.append({"label": display_label, "rarity": rarity})

    return guaranteed_drops, probability_drops


class TaskBoardView(LoginRequiredMixin, TemplateView):
    """任务面板页面"""

    template_name = "gameplay/tasks.html"

    def _build_mission_data(
        self,
        missions: list[MissionTemplate],
        attempts: dict[str, int],
        extra_attempts: dict[str, int],
    ) -> list[dict[str, Any]]:
        mission_data: list[dict[str, Any]] = []
        for mission in missions:
            used = attempts.get(mission.key, 0)
            extra = extra_attempts.get(mission.key, 0)
            daily_limit = mission.daily_limit + extra
            remaining = max(0, daily_limit - used)
            mission_data.append(
                {
                    "mission": mission,
                    "used": used,
                    "remaining": remaining,
                    "daily_limit": daily_limit,
                    "extra": extra,
                }
            )
        return mission_data

    def _build_selection_summary(
        self,
        selected_key: str | None,
        missions_by_key: dict[str, MissionTemplate],
        attempts: dict[str, int],
        extra_attempts: dict[str, int],
    ) -> tuple[MissionTemplate | None, int, int, int]:
        selected_mission = missions_by_key.get(selected_key) if selected_key else None
        selected_attempts = attempts.get(selected_key, 0) if selected_key else 0
        selected_extra = extra_attempts.get(selected_key, 0) if selected_key else 0
        selected_daily_limit = (selected_mission.daily_limit + selected_extra) if selected_mission else 0
        selected_remaining = max(0, selected_daily_limit - selected_attempts)
        return selected_mission, selected_attempts, selected_daily_limit, selected_remaining

    def _build_troop_config(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        from battle.troops import load_troop_templates

        troop_templates = load_troop_templates()
        troop_template_items = sorted(
            troop_templates.items(),
            key=lambda item: safe_int(item[1].get("priority"), default=0) or 0,
        )
        config_items = [
            {
                "key": key,
                "label": data.get("label", key),
                "description": data.get("description", "") or "",
                "value": 0,
            }
            for key, data in troop_template_items
        ]
        return troop_templates, config_items

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        refresh_mission_runs(manor, prefer_async=True)
        missions = list(MissionTemplate.objects.all().order_by("id"))
        missions_by_key = {mission.key: mission for mission in missions}
        attempts = bulk_mission_attempts_today(manor, missions)
        extra_attempts = bulk_get_mission_extra_attempts(manor, missions)
        enemy_keys, troop_keys, drop_keys = _collect_mission_asset_keys(missions)
        guest_templates = {
            tpl.key: tpl for tpl in GuestTemplate.objects.filter(key__in=enemy_keys).only("key", "name", "avatar")
        }
        guest_labels = {key: tpl.name for key, tpl in guest_templates.items()}

        # 加载士兵模板
        from battle.models import TroopTemplate

        troop_templates_objs = {
            tpl.key: tpl for tpl in TroopTemplate.objects.filter(key__in=troop_keys).only("key", "name")
        }

        from gameplay.utils.template_loader import get_item_templates_by_keys

        item_templates = get_item_templates_by_keys(drop_keys)
        loot_labels = {key: tpl.name for key, tpl in item_templates.items()}
        loot_rarities = {key: (tpl.rarity or "default") for key, tpl in item_templates.items()}
        book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=drop_keys)}
        loot_labels.update(book_labels)

        mission_data = self._build_mission_data(missions, attempts, extra_attempts)
        selected_key = self.request.GET.get("mission")
        selected_mission, selected_attempts, selected_daily_limit, selected_remaining = self._build_selection_summary(
            selected_key,
            missions_by_key,
            attempts,
            extra_attempts,
        )
        available_guests = (
            manor.guests.filter(status=GuestStatus.IDLE)
            .select_related("template")
            .only(
                "id",
                "level",
                "current_hp",
                "status",
                "custom_name",
                "hp_bonus",
                "defense_stat",  # max_hp 计算所需
                "template__id",
                "template__key",
                "template__name",
                "template__avatar",
                "template__rarity",
            )
        )

        # 获取任务卡数量
        mission_card_count = get_item_quantity(manor, MISSION_CARD_KEY)

        troop_templates, config_items = self._build_troop_config()
        active_runs = (
            manor.mission_runs.select_related("mission", "battle_report")
            .prefetch_related(Prefetch("guests", queryset=Guest.objects.select_related("template")))
            .filter(status=MissionRun.Status.ACTIVE)
            .order_by("-started_at")[: UIConstants.ACTIVE_RUNS_DISPLAY]
        )
        context["manor"] = manor
        context["missions"] = missions
        context["attempts_today"] = attempts
        context["mission_data"] = mission_data
        context["selected_mission"] = selected_mission
        context["selected_attempts"] = selected_attempts
        context["selected_remaining"] = selected_remaining
        context["selected_daily_limit"] = selected_daily_limit
        context["mission_card_count"] = mission_card_count
        drop_labels = dict(ResourceType.choices)
        drop_labels.update(loot_labels)
        context["selected_drop_items"] = []
        context["selected_probability_drop_items"] = []
        if selected_mission:
            guaranteed_drops, probability_drops = _build_drop_lists(
                selected_mission,
                drop_labels,
                item_templates,
                book_labels,
                loot_rarities,
            )
            context["selected_drop_items"] = guaranteed_drops
            context["selected_probability_drop_items"] = probability_drops
        context["available_guests"] = available_guests
        context["troop_config"] = config_items
        context["player_troops"] = get_player_troops(manor)
        context["active_runs"] = active_runs
        combined_labels = dict(ResourceType.choices)
        combined_labels.update(loot_labels)
        context["resource_labels"] = combined_labels
        context["guest_labels"] = guest_labels
        context["guest_templates"] = guest_templates
        context["troop_templates_objs"] = troop_templates_objs
        context["troop_labels"] = {key: data.get("label", key) for key, data in troop_templates.items()}
        context["max_squad"] = getattr(manor, "max_squad_size", 5)
        return context


@method_decorator(require_POST, name="dispatch")
class AcceptMissionView(LoginRequiredMixin, TemplateView):
    """接受任务出征"""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        manor = ensure_manor(request.user)
        mission, redirect_response = _resolve_mission_or_redirect(request, request.POST.get("mission_key"))
        if redirect_response is not None:
            return redirect_response
        if mission is None:
            return _mission_tasks_redirect()

        if mission.is_defense:
            guest_ids = []
            raw_loadout = {}
        else:
            raw_guest_ids = request.POST.getlist("guest_ids")
            guest_ids = _parse_positive_ids(raw_guest_ids)
            if guest_ids is None:
                messages.error(request, "门客选择有误")
                return _mission_tasks_redirect(mission.key)
            limit = getattr(manor, "max_squad_size", 5)
            if len(guest_ids) > limit:
                messages.error(request, f"本次出征最多选择 {limit} 名门客")
                return _mission_tasks_redirect(mission.key)
            if mission.guest_only:
                raw_loadout = {}
            else:
                raw_loadout = {}
                from battle.troops import troop_template_list

                for item in troop_template_list():
                    raw_value = request.POST.get(f"troop_{item['key']}", 0)
                    quantity = safe_int(raw_value, default=None, min_val=0)
                    if quantity is None:
                        messages.error(request, "护院配置有误")
                        return _mission_tasks_redirect(mission.key)
                    raw_loadout[item["key"]] = quantity

        lock_ok, lock_key, lock_token = _acquire_mission_action_lock("accept", int(manor.id), mission.key)
        if not lock_ok:
            messages.warning(request, "任务请求处理中，请稍候重试")
            return _mission_tasks_redirect(mission.key)

        try:
            try:
                loadout = normalize_mission_loadout(raw_loadout) if raw_loadout else {}
                launch_mission(manor, mission, guest_ids, loadout)
                if mission.is_defense:
                    messages.success(request, f"{mission.name} 已进入防守，战报稍后送达。")
                else:
                    messages.success(request, f"{mission.name} 已出征，战报稍后送达。")
            except (GameError, ValueError) as exc:
                _handle_known_mission_error(request, exc)
            except Exception as exc:
                _handle_unexpected_mission_error(
                    request,
                    exc,
                    log_message="Unexpected mission accept error: manor_id=%s user_id=%s mission_key=%s mission_id=%s",
                    log_args=(
                        getattr(manor, "id", None),
                        getattr(request.user, "id", None),
                        mission.key,
                        getattr(mission, "id", None),
                    ),
                )
        finally:
            _release_mission_action_lock(lock_key, lock_token)
        return _mission_tasks_redirect(mission.key)


@login_required
@require_POST
def retreat_mission_view(request: HttpRequest, pk: int) -> HttpResponse:
    """任务撤退"""
    manor = ensure_manor(request.user)
    run = get_object_or_404(
        manor.mission_runs.select_related("mission"),
        pk=pk,
        status=MissionRun.Status.ACTIVE,
    )
    lock_ok, lock_key, lock_token = _acquire_mission_action_lock("retreat_mission", int(manor.id), str(pk))
    if not lock_ok:
        messages.warning(request, "任务请求处理中，请稍候重试")
        return redirect("gameplay:dashboard")

    try:
        try:
            request_retreat(run)
            eta = run.return_at.strftime("%H:%M:%S") if run.return_at else ""
            messages.info(request, f"{run.mission.name} 已撤退，预计返程：{eta}")
        except (GameError, ValueError) as exc:
            _handle_known_mission_error(request, exc)
        except Exception as exc:
            _handle_unexpected_mission_error(
                request,
                exc,
                log_message="Unexpected mission retreat error: manor_id=%s user_id=%s run_id=%s mission_id=%s",
                log_args=(
                    getattr(manor, "id", None),
                    getattr(request.user, "id", None),
                    pk,
                    getattr(run, "mission_id", None),
                ),
            )
    finally:
        _release_mission_action_lock(lock_key, lock_token)
    return redirect("gameplay:dashboard")


@login_required
@require_POST
def retreat_scout_view(request: HttpRequest, pk: int) -> HttpResponse:
    """侦察撤退视图"""
    from gameplay.models import ScoutRecord
    from gameplay.services.raid import request_scout_retreat

    manor = ensure_manor(request.user)
    record = get_object_or_404(
        ScoutRecord.objects.select_related("defender"),
        pk=pk,
        attacker=manor,
        status=ScoutRecord.Status.SCOUTING,
    )
    lock_ok, lock_key, lock_token = _acquire_mission_action_lock("retreat_scout", int(manor.id), str(pk))
    if not lock_ok:
        messages.warning(request, "任务请求处理中，请稍候重试")
        return redirect("home")

    try:
        try:
            request_scout_retreat(record)
            messages.info(request, f"侦察 {record.defender.display_name} 已撤退，探子正在返程")
        except (GameError, ValueError) as exc:
            _handle_known_mission_error(request, exc)
        except Exception as exc:
            _handle_unexpected_mission_error(
                request,
                exc,
                log_message="Unexpected scout retreat error: manor_id=%s user_id=%s record_id=%s defender_id=%s",
                log_args=(
                    getattr(manor, "id", None),
                    getattr(request.user, "id", None),
                    pk,
                    getattr(record, "defender_id", None),
                ),
            )
    finally:
        _release_mission_action_lock(lock_key, lock_token)
    return redirect("home")


@login_required
@require_POST
def use_mission_card_view(request: HttpRequest) -> HttpResponse:
    """
    使用任务卡增加任务次数。

    消耗一张任务卡，为指定任务增加1次今日额外次数。
    """
    from django.db import transaction

    manor = ensure_manor(request.user)
    mission, redirect_response = _resolve_mission_or_redirect(request, request.POST.get("mission_key"))
    if redirect_response is not None:
        return redirect_response
    if mission is None:
        return _mission_tasks_redirect()

    lock_ok, lock_key, lock_token = _acquire_mission_action_lock("use_card", int(manor.id), mission.key)
    if not lock_ok:
        messages.warning(request, "任务请求处理中，请稍候重试")
        return _mission_tasks_redirect(mission.key)

    try:
        try:
            # 使用事务确保原子性：消耗任务卡和增加次数必须同时成功或同时失败
            with transaction.atomic():
                # 消耗任务卡（内部会检查数量并抛出异常）
                from gameplay.services.inventory import consume_inventory_item_for_manor_locked

                consume_inventory_item_for_manor_locked(manor, MISSION_CARD_KEY, 1)
                # 增加额外次数
                add_mission_extra_attempt(manor, mission, 1)
            messages.success(request, f"使用任务卡成功，{mission.name} 今日次数+1")
        except (GameError, ValueError) as exc:
            # 任务卡不足等业务错误
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            _handle_unexpected_mission_error(
                request,
                exc,
                log_message="Unexpected mission card use error: manor_id=%s user_id=%s mission_key=%s mission_id=%s",
                log_args=(
                    getattr(manor, "id", None),
                    getattr(request.user, "id", None),
                    mission.key,
                    getattr(mission, "id", None),
                ),
            )
    finally:
        _release_mission_action_lock(lock_key, lock_token)

    return _mission_tasks_redirect(mission.key)
