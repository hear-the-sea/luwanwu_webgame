from __future__ import annotations

from typing import Any, Dict

from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView

from common.constants.resources import ResourceType
from guests.models import Guest, GuestTemplate, SkillBook

from .models import BattleReport
from .troops import load_troop_templates

_RESOURCE_LABELS = {
    # Use shared resource enum labels to avoid duplicated hard-coded mappings.
    key: label
    for key, label in ResourceType.choices
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
        # 3) 竞技场公开战报（通过 ArenaMatch 关联）
        return BattleReport.objects.filter(
            Q(manor=manor) | Q(messages__manor=manor) | Q(arena_matches__isnull=False)
        ).distinct()

    @staticmethod
    def _collect_template_keys(attacker_team: list[dict[str, Any]], defender_team: list[dict[str, Any]]) -> set[str]:
        template_keys: set[str] = set()
        for member in attacker_team + defender_team:
            key = member.get("template_key")
            if key:
                template_keys.add(key)
        return template_keys

    @staticmethod
    def _extract_valid_guest_ids(team: list[dict[str, Any]]) -> set[int]:
        ids: set[int] = set()
        for member in team:
            raw_id = member.get("guest_id")
            try:
                guest_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if guest_id > 0:
                ids.add(guest_id)
        return ids

    @classmethod
    def _infer_side_from_guest_ownership(cls, report: BattleReport, manor_id: int) -> str | None:
        attacker_ids = cls._extract_valid_guest_ids(report.attacker_team or [])
        defender_ids = cls._extract_valid_guest_ids(report.defender_team or [])
        candidate_ids = attacker_ids | defender_ids
        if not candidate_ids:
            return None

        owned_ids = set(Guest.objects.filter(manor_id=manor_id, id__in=candidate_ids).values_list("id", flat=True))
        if not owned_ids:
            return None

        attacker_owned_count = len(attacker_ids & owned_ids)
        defender_owned_count = len(defender_ids & owned_ids)
        if attacker_owned_count > defender_owned_count:
            return "attacker"
        if defender_owned_count > attacker_owned_count:
            return "defender"
        return None

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
        if player_side == "spectator":
            return (
                report.attacker_team or [],
                report.defender_team or [],
                report.attacker_troops or {},
                report.defender_troops or {},
                losses.get("attacker", {}),
                losses.get("defender", {}),
            )
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

    @staticmethod
    def _resolve_raid_run(report: BattleReport):
        RaidRun = apps.get_model("gameplay", "RaidRun")
        return RaidRun.objects.filter(battle_report=report).first()

    def _resolve_display_drops(
        self,
        report: BattleReport,
        player_won: bool,
        player_side: str,
        raid_run=None,
    ) -> dict[str, int]:
        raid_run = raid_run or self._resolve_raid_run(report)
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

    def _resolve_display_losses(self, player_won: bool, player_side: str, raid_run) -> dict[str, int]:
        if player_won or player_side == "spectator" or not raid_run:
            return {}

        losses: dict[str, int] = {}
        # 踢馆中仅防守失败会产生资源/物品掠夺损失。
        if player_side == "defender":
            self._merge_nonzero_drops(losses, raid_run.loot_resources or {})
            self._merge_nonzero_drops(losses, raid_run.loot_items or {})
        return losses

    @staticmethod
    def _resolve_capture_loss_label(player_side: str, raid_run) -> str:
        if not raid_run:
            return ""
        battle_rewards = raid_run.battle_rewards or {}
        capture_payload = battle_rewards.get("capture")
        if not isinstance(capture_payload, dict):
            return ""
        capture_from = str(capture_payload.get("from") or "").strip()
        if capture_from != player_side:
            return ""
        guest_name = str(capture_payload.get("guest_name") or "").strip()
        if not guest_name:
            return ""
        return f"门客被俘（{guest_name}）"

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

        is_spectator = player_side == "spectator"
        if is_spectator:
            left_name = getattr(report.manor, "display_name", "") or "进攻方"
            right_name = (report.opponent_name or "").strip() or "防守方"
            context["report_title"] = f"{left_name} vs {right_name} 战报"
        elif player_side == "defender" and report.manor_id != manor.id:
            attacker_name = getattr(report.manor, "display_name", "") or ""
            context["report_title"] = f"{attacker_name or report.opponent_name} 战报"
        else:
            context["report_title"] = f"{report.opponent_name} 战报"

        # 判断玩家是否胜利（观战视角不参与胜负判定）
        player_won = (report.winner == player_side) if not is_spectator else False
        context["player_won"] = player_won
        context["player_side"] = player_side
        context["is_spectator"] = is_spectator

        if is_spectator:
            context["left_team_title"] = "进攻方"
            context["right_team_title"] = "防守方"
            context["left_loss_title"] = "进攻方损失"
            context["right_loss_title"] = "防守方损失"
            if report.winner == "attacker":
                context["spectator_result"] = "本场结果：进攻方胜利"
            elif report.winner == "defender":
                context["spectator_result"] = "本场结果：防守方胜利"
            else:
                context["spectator_result"] = "本场结果：不分胜负"
        else:
            context["left_team_title"] = "我方"
            context["right_team_title"] = "敌方"
            context["left_loss_title"] = "我方损失"
            context["right_loss_title"] = "敌方损失"

        # 传递我方/敌方的 side 标识，用于战斗回合事件筛选
        context["my_side"] = "attacker" if is_spectator else player_side
        context["enemy_side"] = "defender" if context["my_side"] == "attacker" else "attacker"

        # 进攻方/防守方标识
        context["is_attacker"] = player_side == "attacker"
        context["is_defender"] = player_side == "defender"

        raid_run = None if is_spectator else self._resolve_raid_run(report)
        drops = (
            report.drops or {}
            if is_spectator
            else self._resolve_display_drops(report, player_won, player_side, raid_run=raid_run)
        )
        item_templates = get_item_template_names_by_keys(drops.keys())
        book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=drops.keys())}
        drop_items = self._build_drop_items(drops, item_templates, book_labels)
        context["drop_items"] = drop_items
        context["has_drops"] = bool(drop_items)

        loss_items: list[dict[str, Any]] = []
        if not is_spectator:
            loss_map = self._resolve_display_losses(player_won, player_side, raid_run)
            loss_item_templates = get_item_template_names_by_keys(loss_map.keys())
            loss_book_labels = {book.key: book.name for book in SkillBook.objects.filter(key__in=loss_map.keys())}
            loss_items = self._build_drop_items(loss_map, loss_item_templates, loss_book_labels)

            capture_loss_label = self._resolve_capture_loss_label(player_side, raid_run)
            if capture_loss_label:
                loss_items.append({"key": "captured_guest", "label": capture_loss_label})

        context["loss_items"] = loss_items
        return context

    def _determine_player_side(self, report: BattleReport, manor) -> str:
        """
        判断当前玩家在战报中的视角（attacker / defender / spectator）。

        判断逻辑：
        1. 检查 MissionRun：如果是防守任务，玩家是 defender
        2. 检查 RaidRun：根据玩家是进攻方还是防守方决定
        3. 检查 ArenaMatch：非参战玩家走 spectator 视角
        4. 默认：战报归属方是 attacker（普通任务）
        """
        MissionRun = apps.get_model("gameplay", "MissionRun")
        RaidRun = apps.get_model("gameplay", "RaidRun")
        ArenaMatch = apps.get_model("gameplay", "ArenaMatch")

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

        # 检查是否为竞技场战报
        arena_match = (
            ArenaMatch.objects.select_related("attacker_entry", "defender_entry").filter(battle_report=report).first()
        )
        if arena_match:
            if arena_match.defender_entry_id:
                defender_manor_id = getattr(arena_match.defender_entry, "manor_id", None)
                if defender_manor_id == manor.id:
                    return "defender"
            attacker_manor_id = getattr(arena_match.attacker_entry, "manor_id", None)
            if attacker_manor_id == manor.id:
                return "attacker"
            return "spectator"

        inferred_side = self._infer_side_from_guest_ownership(report, manor.id)
        if inferred_side:
            return inferred_side

        # 兜底逻辑：当关联记录缺失时，优先用战报归属方与消息接收方推断视角，
        # 防止防守方回落到 attacker 视角。
        if report.manor_id == manor.id:
            return "attacker"
        if report.messages.filter(manor_id=manor.id).exists():
            return "defender"

        # 默认：战报归属方是进攻方（普通任务）
        return "attacker"
