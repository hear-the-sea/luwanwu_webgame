from __future__ import annotations

from typing import Dict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView

from gameplay.models import MissionRun, RaidRun, ResourceType
from gameplay.services import ensure_manor
from gameplay.utils.template_loader import get_item_template_names_by_keys
from guests.models import GuestTemplate, SkillBook

from .models import BattleReport
from .troops import load_troop_templates


class BattleReportDetailView(LoginRequiredMixin, DetailView):
    template_name = "battle/report_detail.html"
    model = BattleReport
    context_object_name = "report"

    def get_queryset(self):
        manor = ensure_manor(self.request.user)
        # 允许查看：
        # 1) 自己作为战报归属方（report.manor）
        # 2) 通过站内信收到的战报（Message.battle_report）
        return (
            BattleReport.objects.filter(Q(manor=manor) | Q(messages__manor=manor))
            .distinct()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report: BattleReport = context["report"]
        manor = ensure_manor(self.request.user)
        troop_definitions = load_troop_templates()

        # 判断玩家视角
        player_side = self._determine_player_side(report, manor)

        # 收集所有需要的 template_key
        attacker_team = report.attacker_team or []
        defender_team = report.defender_team or []
        all_template_keys = set()
        for member in attacker_team + defender_team:
            if member.get("template_key"):
                all_template_keys.add(member["template_key"])

        # 查询门客模板获取头像URL
        avatar_map: Dict[str, str] = {}
        if all_template_keys:
            templates = GuestTemplate.objects.filter(key__in=all_template_keys)
            for tpl in templates:
                if tpl.avatar:
                    avatar_map[tpl.key] = tpl.avatar.url

        # 为每个门客添加头像URL
        for member in attacker_team:
            member["avatar_url"] = avatar_map.get(member.get("template_key", ""), "")
        for member in defender_team:
            member["avatar_url"] = avatar_map.get(member.get("template_key", ""), "")

        # 根据玩家视角设置我方/敌方显示
        if player_side == "defender":
            # 玩家是防守方
            my_team = defender_team
            enemy_team = attacker_team
            my_troops_raw = report.defender_troops or {}
            enemy_troops_raw = report.attacker_troops or {}
            losses = report.losses or {}
            my_loss = losses.get("defender", {})
            enemy_loss = losses.get("attacker", {})
        else:
            # 玩家是进攻方
            my_team = attacker_team
            enemy_team = defender_team
            my_troops_raw = report.attacker_troops or {}
            enemy_troops_raw = report.defender_troops or {}
            losses = report.losses or {}
            my_loss = losses.get("attacker", {})
            enemy_loss = losses.get("defender", {})

        context["attacker_team_display"] = my_team
        context["defender_team_display"] = enemy_team
        context["attacker_troops"] = [
            {
                "key": key,
                "label": troop_definitions.get(key, {}).get("label", key),
                "count": count,
                "avatar": troop_definitions.get(key, {}).get("avatar"),
            }
            for key, count in my_troops_raw.items()
            if count
        ]
        context["defender_troops"] = [
            {
                "key": key,
                "label": troop_definitions.get(key, {}).get("label", key),
                "count": count,
                "avatar": troop_definitions.get(key, {}).get("avatar"),
            }
            for key, count in enemy_troops_raw.items()
            if count
        ]
        context["attacker_loss"] = my_loss
        context["defender_loss"] = enemy_loss

        # 判断玩家是否胜利
        player_won = report.winner == player_side
        context["player_won"] = player_won
        context["player_side"] = player_side

        # 传递我方/敌方的 side 标识，用于战斗回合事件筛选
        context["my_side"] = player_side
        context["enemy_side"] = "defender" if player_side == "attacker" else "attacker"

        # 进攻方/防守方标识
        context["is_attacker"] = player_side == "attacker"
        context["is_defender"] = player_side == "defender"

        drops = report.drops or {}
        raid_run = RaidRun.objects.filter(battle_report=report).first()
        if raid_run:
            drops = {}
            if player_won:
                if player_side == "attacker":
                    for key, amount in (raid_run.loot_resources or {}).items():
                        if amount:
                            drops[key] = drops.get(key, 0) + amount
                    for key, amount in (raid_run.loot_items or {}).items():
                        if amount:
                            drops[key] = drops.get(key, 0) + amount
                battle_rewards = raid_run.battle_rewards or {}
                exp_fruit = battle_rewards.get("exp_fruit", 0)
                if exp_fruit:
                    drops["experience_fruit"] = drops.get("experience_fruit", 0) + int(exp_fruit)
                equipment = battle_rewards.get("equipment", {}) or {}
                for key, amount in equipment.items():
                    if amount:
                        drops[key] = drops.get(key, 0) + amount
        item_templates = get_item_template_names_by_keys(drops.keys())
        book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=drops.keys())}
        drop_items = []
        for key, amount in drops.items():
            label = key
            try:
                label = ResourceType(key).label
            except ValueError:
                label = item_templates.get(key, book_labels.get(key, key))
            drop_items.append({"key": key, "label": label, "amount": amount})
        context["drop_items"] = drop_items
        context["has_drops"] = bool(drop_items)
        return context

    def _determine_player_side(self, report: BattleReport, manor) -> str:
        """
        判断当前玩家在战报中的视角（attacker 或 defender）。

        判断逻辑：
        1. 检查 MissionRun：如果是防守任务，玩家是 defender
        2. 检查 RaidRun：根据玩家是进攻方还是防守方决定
        3. 默认：战报归属方是 attacker（普通任务）
        """
        # 检查是否为防守任务
        mission_run = MissionRun.objects.filter(battle_report=report).select_related("mission").first()
        if mission_run and mission_run.mission.is_defense:
            return "defender"

        # 检查是否为踢馆战报
        raid_run = RaidRun.objects.filter(battle_report=report).first()
        if raid_run:
            # 踢馆战报：根据当前用户是进攻方还是防守方决定视角
            if raid_run.defender_id == manor.id:
                return "defender"
            else:
                return "attacker"

        # 默认：战报归属方是进攻方（普通任务）
        return "attacker"
