"""
任务系统视图：任务面板、出征、撤退
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from django.db.models import Prefetch

from core.exceptions import GameError
from core.utils import safe_int_list, sanitize_error_message
from guests.models import Guest, GuestStatus, GuestTemplate, SkillBook

from gameplay.constants import UIConstants
from gameplay.models import MissionRun, MissionTemplate, ResourceType
from gameplay.services import (
    bulk_mission_attempts_today,
    bulk_get_mission_extra_attempts,
    ensure_manor,
    launch_mission,
    normalize_mission_loadout,
    refresh_manor_state,
    refresh_mission_runs,
    request_retreat,
    add_mission_extra_attempt,
    get_item_quantity,
)
from gameplay.services.recruitment import get_player_troops

# 任务卡道具 key
MISSION_CARD_KEY = "mission_card"


class TaskBoardView(LoginRequiredMixin, TemplateView):
    """任务面板页面"""

    template_name = "gameplay/tasks.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        refresh_mission_runs(manor)
        missions = list(MissionTemplate.objects.all().order_by("id"))
        missions_by_key = {mission.key: mission for mission in missions}
        attempts = bulk_mission_attempts_today(manor, missions)
        extra_attempts = bulk_get_mission_extra_attempts(manor, missions)
        enemy_keys = set()
        troop_keys = set()
        drop_keys = set()
        for mission in missions:
            # enemy_guests 支持字符串和字典两种格式
            for entry in (mission.enemy_guests or []):
                if isinstance(entry, str):
                    enemy_keys.add(entry)
                elif isinstance(entry, dict):
                    key = entry.get("key")
                    if key:
                        enemy_keys.add(key)
            troop_keys.update((mission.enemy_troops or {}).keys())
            drop_keys.update((mission.drop_table or {}).keys())
        guest_templates = {tpl.key: tpl for tpl in GuestTemplate.objects.filter(key__in=enemy_keys).only('key', 'name', 'avatar')}
        guest_labels = {key: tpl.name for key, tpl in guest_templates.items()}

        # 加载士兵模板
        from battle.models import TroopTemplate
        troop_templates_objs = {tpl.key: tpl for tpl in TroopTemplate.objects.filter(key__in=troop_keys).only('key', 'name')}

        from gameplay.utils.template_loader import get_item_templates_by_keys
        item_templates = get_item_templates_by_keys(drop_keys)
        loot_labels = {key: tpl.name for key, tpl in item_templates.items()}
        loot_rarities = {key: (tpl.rarity or "default") for key, tpl in item_templates.items()}
        book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=drop_keys)}
        loot_labels.update(book_labels)

        # 计算每个任务的剩余次数（包含额外次数）
        mission_data = []
        for mission in missions:
            used = attempts.get(mission.key, 0)
            extra = extra_attempts.get(mission.key, 0)
            daily_limit = mission.daily_limit + extra
            remaining = max(0, daily_limit - used)
            mission_data.append({
                "mission": mission,
                "used": used,
                "remaining": remaining,
                "daily_limit": daily_limit,
                "extra": extra,
            })
        selected_key = self.request.GET.get("mission")
        selected_mission = missions_by_key.get(selected_key) if selected_key else None
        selected_attempts = attempts.get(selected_key, 0) if selected_key else 0
        selected_extra = extra_attempts.get(selected_key, 0) if selected_key else 0
        selected_daily_limit = (
            (selected_mission.daily_limit + selected_extra) if selected_mission else 0
        )
        selected_remaining = max(0, selected_daily_limit - selected_attempts)
        available_guests = manor.guests.filter(status=GuestStatus.IDLE).select_related("template").only(
            'id', 'display_name', 'level', 'current_hp', 'max_hp', 'status',
            'template__id', 'template__key', 'template__name', 'template__avatar'
        )

        # 获取任务卡数量
        mission_card_count = get_item_quantity(manor, MISSION_CARD_KEY)

        from battle.troops import load_troop_templates

        troop_templates = load_troop_templates()
        troop_template_items = sorted(
            troop_templates.items(),
            key=lambda item: int(item[1].get("priority") or 0),
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
        active_runs = (
            manor.mission_runs.select_related("mission", "battle_report")
            .prefetch_related(Prefetch("guests", queryset=Guest.objects.select_related("template")))
            .filter(status=MissionRun.Status.ACTIVE)
            .order_by("-started_at")[:UIConstants.ACTIVE_RUNS_DISPLAY]
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
            # 分离guaranteed drops和probability drops
            drops = selected_mission.drop_table or {}
            guaranteed_drops = []
            probability_drops_from_table = []

            def parse_drop_value(value):
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
                    if number is not None and number < 1 and number > 0:
                        chance = number
                        count = 1
                    elif number is not None and number >= 1:
                        count = int(number)
                if chance is not None and count is None:
                    count = 1
                return chance, count

            for key, val in drops.items():
                label = drop_labels.get(key, key)
                if label == key:  # fallback: use pre-loaded templates
                    tpl = item_templates.get(key)
                    if tpl:
                        label = tpl.name
                    elif key in book_labels:
                        label = book_labels[key]

                chance, count = parse_drop_value(val)

                rarity = loot_rarities.get(key) or "default"

                # 区分概率掉落（<1）和确定掉落（>=1）
                if chance is not None and chance < 1 and chance > 0:
                    # 概率掉落 - 不显示具体概率
                    display_label = label
                    if count and count > 1:
                        display_label = f"{label} x{count}"
                    probability_drops_from_table.append({"label": display_label, "rarity": rarity})
                else:
                    # 确定掉落
                    display_label = label
                    if count is not None and count >= 1:
                        display_label = f"{label} x{count}"
                    guaranteed_drops.append({"label": display_label, "rarity": rarity})

            context["selected_drop_items"] = guaranteed_drops

            # 处理probability_drop_table中的概率掉落
            probability_drops = selected_mission.probability_drop_table or {}
            for key, val in probability_drops.items():
                label = drop_labels.get(key, key)
                if label == key:  # fallback: use pre-loaded templates
                    tpl = item_templates.get(key)
                    if tpl:
                        label = tpl.name
                    elif key in book_labels:
                        label = book_labels[key]

                chance, count = parse_drop_value(val)

                display_label = label
                # 只显示名称和数量，不显示概率
                if count is not None and count >= 1:
                    display_label = f"{label} x{count}"

                rarity = loot_rarities.get(key) or "default"
                probability_drops_from_table.append({"label": display_label, "rarity": rarity})

            context["selected_probability_drop_items"] = probability_drops_from_table
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
        mission_key = request.POST.get("mission_key")
        mission = get_object_or_404(MissionTemplate, key=mission_key)
        if mission.is_defense:
            guest_ids = []
            raw_loadout = {}
        else:
            guest_ids = safe_int_list(request.POST.getlist("guest_ids"))
            if not guest_ids and request.POST.getlist("guest_ids"):
                messages.error(request, "门客选择有误")
                return redirect(f"{reverse('gameplay:tasks')}?mission={mission.key}")
            limit = getattr(manor, "max_squad_size", 5)
            if len(guest_ids) > limit:
                messages.error(request, f"本次出征最多选择 {limit} 名门客")
                return redirect(f"{reverse('gameplay:tasks')}?mission={mission.key}")
            if mission.guest_only:
                raw_loadout = {}
            else:
                raw_loadout = {}
                from battle.troops import troop_template_list
                for item in troop_template_list():
                    raw_loadout[item["key"]] = request.POST.get(f"troop_{item['key']}", 0)
        try:
            loadout = normalize_mission_loadout(raw_loadout) if raw_loadout else {}
            launch_mission(manor, mission, guest_ids, loadout)
            if mission.is_defense:
                messages.success(request, f"{mission.name} 已进入防守，战报稍后送达。")
            else:
                messages.success(request, f"{mission.name} 已出征，战报稍后送达。")
        except ValueError as exc:
            messages.error(request, sanitize_error_message(exc))
        return redirect(f"{reverse('gameplay:tasks')}?mission={mission.key}")


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
    try:
        request_retreat(run)
        eta = run.return_at.strftime("%H:%M:%S") if run.return_at else ""
        messages.info(request, f"{run.mission.name} 已撤退，预计返程：{eta}")
    except ValueError as exc:
        messages.error(request, sanitize_error_message(exc))
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
    try:
        request_scout_retreat(record)
        messages.info(request, f"侦察 {record.defender.display_name} 已撤退，探子正在返程")
    except ValueError as exc:
        messages.error(request, sanitize_error_message(exc))
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
    mission_key = request.POST.get("mission_key")

    if not mission_key:
        messages.error(request, "请选择任务")
        return redirect("gameplay:tasks")

    mission = get_object_or_404(MissionTemplate, key=mission_key)

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
        messages.error(request, sanitize_error_message(exc))

    return redirect(f"{reverse('gameplay:tasks')}?mission={mission.key}")
