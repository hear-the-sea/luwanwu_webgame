from __future__ import annotations

from typing import Any, Dict

from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView

from guests.models import GuestTemplate, SkillBook

from .models import BattleReport
from .troops import load_troop_templates

_RESOURCE_LABELS = {
    # Mirror gameplay.models.ResourceType labels but avoid importing gameplay at import-time (reduces app coupling).
    "grain": "粮食",
    "silver": "银两",
}


class BattleReportDetailView(LoginRequiredMixin, DetailView):
    template_name = "battle/report_detail.html"
    model = BattleReport
    context_object_name = "report"

    def get_queryset(self):
        from gameplay.services.manor.core import ensure_manor

        manor = ensure_manor(self.request.user)
        # 允许查看：
        # 1) 自己作为战报归属方（report.manor）
        # 2) 通过站内信收到的战报（Message.battle_report）
        return BattleReport.objects.filter(Q(manor=manor) | Q(messages__manor=manor)).distinct()

    @staticmethod
    def _collect_template_keys(attacker_team: list[dict[str, Any]], defender_team: list[dict[str, Any]]) -> set[str]:
        template_keys: set[str] = set()
        for member in attacker_team + defender_team:
            key = member.get("template_key")
            if key:
                template_keys.add(key)
        return template_keys

    @staticmethod
    def _load_avatar_map(template_keys: set[str]) -> Dict[str, str]:
        avatar_map: Dict[str, str] = {}
        if not template_keys:
            return avatar_map

        templates = GuestTemplate.objects.filter(key__in=template_keys)
        for tpl in templates:
            if tpl.avatar:
                avatar_map[tpl.key] = tpl.avatar.url
        return avatar_map

    @staticmethod
    def _attach_avatar_urls(team: list[dict[str, Any]], avatar_map: Dict[str, str]) -> None:
        for member in team:
            member["avatar_url"] = avatar_map.get(member.get("template_key", ""), "")

    @staticmethod
    def _resolve_perspective(report: BattleReport, player_side: str) -> tuple:
        losses = report.losses or {}
        if player_side == "defender":
            return (
                report.defender_team or [],
                report.attacker_team or [],
                report.defender_troops or {},
                report.attacker_troops or {},
                losses.get("defender", {}),
                losses.get("attacker", {}),
            )
        return (
            report.attacker_team or [],
            report.defender_team or [],
            report.attacker_troops or {},
            report.defender_troops or {},
            losses.get("attacker", {}),
            losses.get("defender", {}),
        )

    @staticmethod
    def _serialize_troops(
        troops_raw: dict[str, int], troop_definitions: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "label": troop_definitions.get(key, {}).get("label", key),
                "count": count,
                "avatar": troop_definitions.get(key, {}).get("avatar"),
            }
            for key, count in troops_raw.items()
            if count
        ]

    @staticmethod
    def _merge_nonzero_drops(target: dict[str, int], source: dict[str, Any]) -> None:
        for key, amount in source.items():
            if amount:
                target[key] = target.get(key, 0) + int(amount)

    def _resolve_display_drops(self, report: BattleReport, player_won: bool, player_side: str) -> dict[str, int]:
        RaidRun = apps.get_model("gameplay", "RaidRun")
        raid_run = RaidRun.objects.filter(battle_report=report).first()
        if not raid_run:
            return report.drops or {}

        drops: dict[str, int] = {}
        if not player_won:
            return drops

        if player_side == "attacker":
            self._merge_nonzero_drops(drops, raid_run.loot_resources or {})
            self._merge_nonzero_drops(drops, raid_run.loot_items or {})

        battle_rewards = raid_run.battle_rewards or {}
        exp_fruit = battle_rewards.get("exp_fruit", 0)
        if exp_fruit:
            drops["experience_fruit"] = drops.get("experience_fruit", 0) + int(exp_fruit)

        equipment = battle_rewards.get("equipment", {}) or {}
        self._merge_nonzero_drops(drops, equipment)
        return drops

    @staticmethod
    def _build_drop_items(
        drops: dict[str, int],
        item_template_names_by_key: dict[str, str],
        skill_book_names_by_key: dict[str, str],
    ) -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "label": _RESOURCE_LABELS.get(key)
                or item_template_names_by_key.get(key)
                or skill_book_names_by_key.get(key)
                or key,
                "amount": amount,
            }
            for key, amount in drops.items()
        ]

    def get_context_data(self, **kwargs):
        from gameplay.services.manor.core import ensure_manor
        from gameplay.utils.template_loader import get_item_template_names_by_keys

        context = super().get_context_data(**kwargs)
        report: BattleReport = context["report"]
        manor = ensure_manor(self.request.user)
        troop_definitions = load_troop_templates()

        # 判断玩家视角
        player_side = self._determine_player_side(report, manor)

        attacker_team = report.attacker_team or []
        defender_team = report.defender_team or []
        template_keys = self._collect_template_keys(attacker_team, defender_team)
        avatar_map = self._load_avatar_map(template_keys)
        self._attach_avatar_urls(attacker_team, avatar_map)
        self._attach_avatar_urls(defender_team, avatar_map)

        my_team, enemy_team, my_troops_raw, enemy_troops_raw, my_loss, enemy_loss = self._resolve_perspective(
            report,
            player_side,
        )

        context["attacker_team_display"] = my_team
        context["defender_team_display"] = enemy_team
        context["attacker_troops"] = self._serialize_troops(my_troops_raw, troop_definitions)
        context["defender_troops"] = self._serialize_troops(enemy_troops_raw, troop_definitions)
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

        drops = self._resolve_display_drops(report, player_won, player_side)
        item_templates = get_item_template_names_by_keys(drops.keys())
        book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=drops.keys())}
        drop_items = self._build_drop_items(drops, item_templates, book_labels)
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
        MissionRun = apps.get_model("gameplay", "MissionRun")
        RaidRun = apps.get_model("gameplay", "RaidRun")

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
