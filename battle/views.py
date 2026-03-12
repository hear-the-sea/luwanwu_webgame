from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import DetailView

from .models import BattleReport
from .troops import load_troop_templates
from .view_helpers import (
    attach_avatar_urls,
    build_report_title,
    build_reward_context,
    build_side_labels,
    collect_template_keys,
    determine_player_side,
    load_avatar_map,
    resolve_capture_loss_label,
    resolve_display_drops,
    resolve_display_losses,
    resolve_perspective,
    resolve_report_raid_run,
    serialize_troops,
)


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

    def get_context_data(self, **kwargs):
        from gameplay.services.manor.core import ensure_manor

        context = super().get_context_data(**kwargs)
        report: BattleReport = context["report"]
        manor = ensure_manor(self.request.user)
        troop_definitions = load_troop_templates()

        # 判断玩家视角
        player_side = determine_player_side(report, manor_id=manor.id)

        attacker_team = report.attacker_team or []
        defender_team = report.defender_team or []
        template_keys = collect_template_keys(attacker_team, defender_team)
        avatar_map = load_avatar_map(template_keys)
        attach_avatar_urls(attacker_team, avatar_map)
        attach_avatar_urls(defender_team, avatar_map)

        my_team, enemy_team, my_troops_raw, enemy_troops_raw, my_loss, enemy_loss = resolve_perspective(
            report,
            player_side,
        )

        context["attacker_team_display"] = my_team
        context["defender_team_display"] = enemy_team
        context["attacker_troops"] = serialize_troops(my_troops_raw, troop_definitions)
        context["defender_troops"] = serialize_troops(enemy_troops_raw, troop_definitions)
        context["attacker_loss"] = my_loss
        context["defender_loss"] = enemy_loss

        side_context = build_side_labels(player_side=player_side, winner=report.winner)
        is_spectator = bool(side_context["is_spectator"])
        player_won = bool(side_context["player_won"])
        context["report_title"] = build_report_title(report, player_side=player_side, viewer_manor_id=manor.id)
        context.update(side_context)

        raid_run = None if is_spectator else resolve_report_raid_run(report)
        drops = (
            report.drops or {}
            if is_spectator
            else resolve_display_drops(report, player_won=player_won, player_side=player_side, raid_run=raid_run)
        )
        loss_map: dict[str, int] = {}
        if not is_spectator:
            loss_map = resolve_display_losses(player_won=player_won, player_side=player_side, raid_run=raid_run)

        capture_loss_label = (
            "" if is_spectator else resolve_capture_loss_label(player_side=player_side, raid_run=raid_run)
        )
        context.update(
            build_reward_context(
                drops=drops,
                loss_map=loss_map,
                capture_loss_label=capture_loss_label,
            )
        )
        return context
