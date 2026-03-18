"""
任务系统视图：任务面板、出征、撤退
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import safe_int
from core.utils.locked_actions import execute_locked_action
from gameplay.constants import UIConstants
from gameplay.models import MissionRun, MissionTemplate, ResourceType
from gameplay.services.inventory.core import get_item_quantity
from gameplay.services.manor.core import get_manor
from gameplay.services.missions_impl.attempts import (
    add_mission_extra_attempt,
    bulk_get_mission_extra_attempts,
    bulk_mission_attempts_today,
)
from gameplay.services.missions_impl.execution import launch_mission, request_retreat
from gameplay.services.missions_impl.loadout import normalize_mission_loadout
from gameplay.services.recruitment.recruitment import get_player_troops
from gameplay.services.resources import sync_resource_production
from guests.models import Guest, GuestStatus, GuestTemplate, SkillBook

from . import mission_helpers

logger = logging.getLogger(__name__)


class TaskBoardView(LoginRequiredMixin, TemplateView):
    """任务面板页面"""

    template_name = "gameplay/tasks.html"

    def _build_mission_data(
        self,
        missions: list[MissionTemplate],
        attempts: dict[str, int],
        extra_attempts: dict[str, int],
    ) -> list[dict[str, Any]]:
        return mission_helpers.build_mission_data(missions, attempts, extra_attempts)

    def _build_selection_summary(
        self,
        selected_key: str | None,
        missions_by_key: dict[str, MissionTemplate],
        attempts: dict[str, int],
        extra_attempts: dict[str, int],
    ) -> tuple[MissionTemplate | None, int, int, int]:
        return mission_helpers.build_selection_summary(selected_key, missions_by_key, attempts, extra_attempts)

    def _build_troop_config(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        return mission_helpers.build_troop_config()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)
        sync_resource_production(manor, persist=False)
        missions = list(MissionTemplate.objects.all().order_by("id"))
        missions_by_key = {mission.key: mission for mission in missions}
        attempts = bulk_mission_attempts_today(manor, missions)
        extra_attempts = bulk_get_mission_extra_attempts(manor, missions)
        enemy_keys, troop_keys, drop_keys = mission_helpers.collect_mission_asset_keys(missions)
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
        mission_card_count = get_item_quantity(manor, mission_helpers.MISSION_CARD_KEY)

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
            guaranteed_drops, probability_drops = mission_helpers.build_drop_lists(
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
        manor = get_manor(request.user)
        mission, redirect_response = mission_helpers.resolve_mission_or_redirect(
            request, request.POST.get("mission_key")
        )
        if redirect_response is not None:
            return redirect_response
        if mission is None:
            return mission_helpers.mission_tasks_redirect()

        if mission.is_defense:
            guest_ids = []
            raw_loadout = {}
        else:
            raw_guest_ids = request.POST.getlist("guest_ids")
            guest_ids = mission_helpers.parse_positive_ids(raw_guest_ids)
            if guest_ids is None:
                messages.error(request, "门客选择有误")
                return mission_helpers.mission_tasks_redirect(mission.key)
            limit = getattr(manor, "max_squad_size", 5)
            if len(guest_ids) > limit:
                messages.error(request, f"本次出征最多选择 {limit} 名门客")
                return mission_helpers.mission_tasks_redirect(mission.key)
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
                        return mission_helpers.mission_tasks_redirect(mission.key)
                    raw_loadout[item["key"]] = quantity

        def _perform_accept() -> None:
            loadout = normalize_mission_loadout(raw_loadout) if raw_loadout else {}
            launch_mission(manor, mission, guest_ids, loadout)
            if mission.is_defense:
                messages.success(request, f"{mission.name} 已进入防守，战报稍后送达。")
            else:
                messages.success(request, f"{mission.name} 已出征，战报稍后送达。")

        def _mission_redirect() -> HttpResponse:
            return mission_helpers.mission_tasks_redirect(mission.key)

        def _on_lock_conflict() -> HttpResponse:
            messages.warning(request, "任务请求处理中，请稍候重试")
            return _mission_redirect()

        def _on_known_error(exc: BaseException) -> HttpResponse:
            mission_helpers.handle_known_mission_error(request, exc)
            return _mission_redirect()

        def _on_database_error(exc: DatabaseError) -> HttpResponse:
            mission_helpers.handle_unexpected_mission_error(
                request,
                exc,
                log_message="Unexpected mission accept error: manor_id=%s user_id=%s mission_key=%s mission_id=%s",
                log_args=(
                    getattr(manor, "id", None),
                    getattr(request.user, "id", None),
                    mission.key,
                    getattr(mission, "id", None),
                ),
                logger_instance=logger,
            )
            return _mission_redirect()

        return execute_locked_action(
            action_name="accept",
            owner_id=int(manor.id),
            scope=mission.key,
            acquire_lock_fn=mission_helpers.acquire_mission_action_lock,
            release_lock_fn=mission_helpers.release_mission_action_lock,
            on_lock_conflict=_on_lock_conflict,
            operation=_perform_accept,
            on_success=lambda _result: _mission_redirect(),
            known_exceptions=(GameError, ValueError),
            on_known_error=_on_known_error,
            on_database_error=_on_database_error,
        )


@login_required
@require_POST
def retreat_mission_view(request: HttpRequest, pk: int) -> HttpResponse:
    """任务撤退"""
    manor = get_manor(request.user)
    run = get_object_or_404(
        manor.mission_runs.select_related("mission"),
        pk=pk,
        status=MissionRun.Status.ACTIVE,
    )

    def _dashboard_redirect() -> HttpResponse:
        return redirect("gameplay:dashboard")

    def _perform_retreat() -> None:
        request_retreat(run)
        eta = run.return_at.strftime("%H:%M:%S") if run.return_at else ""
        messages.info(request, f"{run.mission.name} 已撤退，预计返程：{eta}")

    def _on_lock_conflict() -> HttpResponse:
        messages.warning(request, "任务请求处理中，请稍候重试")
        return _dashboard_redirect()

    def _on_known_error(exc: BaseException) -> HttpResponse:
        mission_helpers.handle_known_mission_error(request, exc)
        return _dashboard_redirect()

    def _on_database_error(exc: DatabaseError) -> HttpResponse:
        mission_helpers.handle_unexpected_mission_error(
            request,
            exc,
            log_message="Unexpected mission retreat error: manor_id=%s user_id=%s run_id=%s mission_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
                getattr(run, "mission_id", None),
            ),
            logger_instance=logger,
        )
        return _dashboard_redirect()

    return execute_locked_action(
        action_name="retreat_mission",
        owner_id=int(manor.id),
        scope=str(pk),
        acquire_lock_fn=mission_helpers.acquire_mission_action_lock,
        release_lock_fn=mission_helpers.release_mission_action_lock,
        on_lock_conflict=_on_lock_conflict,
        operation=_perform_retreat,
        on_success=lambda _result: _dashboard_redirect(),
        known_exceptions=(GameError, ValueError),
        on_known_error=_on_known_error,
        on_database_error=_on_database_error,
    )


@login_required
@require_POST
def retreat_scout_view(request: HttpRequest, pk: int) -> HttpResponse:
    """侦察撤退视图"""
    from gameplay.models import ScoutRecord
    from gameplay.services.raid import request_scout_retreat

    manor = get_manor(request.user)
    record = get_object_or_404(
        ScoutRecord.objects.select_related("defender"),
        pk=pk,
        attacker=manor,
        status=ScoutRecord.Status.SCOUTING,
    )

    def _home_redirect() -> HttpResponse:
        return redirect("home")

    def _perform_retreat() -> None:
        request_scout_retreat(record)
        messages.info(request, f"侦察 {record.defender.display_name} 已撤退，探子正在返程")

    def _on_lock_conflict() -> HttpResponse:
        messages.warning(request, "任务请求处理中，请稍候重试")
        return _home_redirect()

    def _on_known_error(exc: BaseException) -> HttpResponse:
        mission_helpers.handle_known_mission_error(request, exc)
        return _home_redirect()

    def _on_database_error(exc: DatabaseError) -> HttpResponse:
        mission_helpers.handle_unexpected_mission_error(
            request,
            exc,
            log_message="Unexpected scout retreat error: manor_id=%s user_id=%s record_id=%s defender_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
                getattr(record, "defender_id", None),
            ),
            logger_instance=logger,
        )
        return _home_redirect()

    return execute_locked_action(
        action_name="retreat_scout",
        owner_id=int(manor.id),
        scope=str(pk),
        acquire_lock_fn=mission_helpers.acquire_mission_action_lock,
        release_lock_fn=mission_helpers.release_mission_action_lock,
        on_lock_conflict=_on_lock_conflict,
        operation=_perform_retreat,
        on_success=lambda _result: _home_redirect(),
        known_exceptions=(GameError, ValueError),
        on_known_error=_on_known_error,
        on_database_error=_on_database_error,
    )


@login_required
@require_POST
def use_mission_card_view(request: HttpRequest) -> HttpResponse:
    """
    使用任务卡增加任务次数。

    消耗一张任务卡，为指定任务增加1次今日额外次数。
    """
    from django.db import transaction

    manor = get_manor(request.user)
    mission, redirect_response = mission_helpers.resolve_mission_or_redirect(request, request.POST.get("mission_key"))
    if redirect_response is not None:
        return redirect_response
    if mission is None:
        return mission_helpers.mission_tasks_redirect()

    def _mission_redirect() -> HttpResponse:
        return mission_helpers.mission_tasks_redirect(mission.key)

    def _perform_use_card() -> None:
        # 使用事务确保原子性：消耗任务卡和增加次数必须同时成功或同时失败
        with transaction.atomic():
            # 消耗任务卡（内部会检查数量并抛出异常）
            from gameplay.services.inventory.core import consume_inventory_item_for_manor_locked

            consume_inventory_item_for_manor_locked(manor, mission_helpers.MISSION_CARD_KEY, 1)
            # 增加额外次数
            add_mission_extra_attempt(manor, mission, 1)
        messages.success(request, f"使用任务卡成功，{mission.name} 今日次数+1")

    def _on_lock_conflict() -> HttpResponse:
        messages.warning(request, "任务请求处理中，请稍候重试")
        return _mission_redirect()

    def _on_known_error(exc: BaseException) -> HttpResponse:
        mission_helpers.handle_known_mission_error(request, exc)
        return _mission_redirect()

    def _on_database_error(exc: DatabaseError) -> HttpResponse:
        mission_helpers.handle_unexpected_mission_error(
            request,
            exc,
            log_message="Unexpected mission card use error: manor_id=%s user_id=%s mission_key=%s mission_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                mission.key,
                getattr(mission, "id", None),
            ),
            logger_instance=logger,
        )
        return _mission_redirect()

    return execute_locked_action(
        action_name="use_card",
        owner_id=int(manor.id),
        scope=mission.key,
        acquire_lock_fn=mission_helpers.acquire_mission_action_lock,
        release_lock_fn=mission_helpers.release_mission_action_lock,
        on_lock_conflict=_on_lock_conflict,
        operation=_perform_use_card,
        on_success=lambda _result: _mission_redirect(),
        known_exceptions=(GameError, ValueError),
        on_known_error=_on_known_error,
        on_database_error=_on_database_error,
    )
