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

from battle.troops import load_troop_templates, troop_template_list
from core.utils import safe_int_list, sanitize_error_message
from guests.models import GuestStatus, GuestTemplate, SkillBook

from ..constants import UIConstants
from ..models import MissionRun, MissionTemplate, ResourceType
from ..services import (
    bulk_mission_attempts_today,
    ensure_manor,
    launch_mission,
    normalize_mission_loadout,
    refresh_manor_state,
    refresh_mission_runs,
    request_retreat,
)
from ..services.recruitment import get_player_troops


class TaskBoardView(LoginRequiredMixin, TemplateView):
    """任务面板页面"""

    template_name = "gameplay/tasks.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        refresh_mission_runs(manor)
        missions_qs = MissionTemplate.objects.all().order_by("id")
        missions = list(missions_qs)
        attempts = bulk_mission_attempts_today(manor, missions)
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
        guest_templates = {tpl.key: tpl for tpl in GuestTemplate.objects.filter(key__in=enemy_keys)}
        guest_labels = {key: tpl.name for key, tpl in guest_templates.items()}

        # 加载士兵模板
        from battle.models import TroopTemplate
        troop_templates_objs = {tpl.key: tpl for tpl in TroopTemplate.objects.filter(key__in=troop_keys)}

        from ..utils.template_loader import get_item_templates_by_keys
        item_templates = get_item_templates_by_keys(drop_keys)
        loot_labels = {key: tpl.name for key, tpl in item_templates.items()}
        loot_rarities = {key: (tpl.rarity or "default") for key, tpl in item_templates.items()}
        book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=drop_keys)}
        loot_labels.update(book_labels)
        mission_data = [
            {
                "mission": mission,
                "used": attempts.get(mission.key, 0),
                "remaining": max(0, mission.daily_limit - attempts.get(mission.key, 0)),
            }
            for mission in missions
        ]
        selected_key = self.request.GET.get("mission")
        selected_mission = missions_qs.filter(key=selected_key).first() if selected_key else None
        selected_attempts = attempts.get(selected_key, 0) if selected_key else 0
        selected_remaining = (
            max(0, selected_mission.daily_limit - selected_attempts) if selected_mission else 0
        )
        available_guests = manor.guests.filter(status=GuestStatus.IDLE).select_related("template")
        config_items = []
        for item in troop_template_list():
            config_items.append(
                {
                    "key": item["key"],
                    "label": item["label"],
                    "description": item.get("description", ""),
                    "value": 0,
                }
            )
        active_runs = (
            manor.mission_runs.select_related("mission")
            .prefetch_related("guests")
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
        troop_templates = load_troop_templates()
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
            raw_loadout = {}
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
    from ..models import ScoutRecord
    from ..services.raid import request_scout_retreat

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
