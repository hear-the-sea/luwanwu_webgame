from __future__ import annotations

import threading
from datetime import timedelta

from django.utils import timezone

from battle.models import BattleReport
from gameplay.models import RaidRun
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.combat import battle as combat_battle


def build_attacker_defender(django_user_model, *, attacker_username: str, defender_username: str):
    attacker_user = django_user_model.objects.create_user(username=attacker_username, password="pass123")
    defender_user = django_user_model.objects.create_user(username=defender_username, password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)
    return attacker, defender


def create_marching_run(attacker, defender, *, battle_due: bool = True) -> RaidRun:
    now = timezone.now()
    return RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        troop_loadout={},
        status=RaidRun.Status.MARCHING,
        travel_time=60,
        battle_at=now - timedelta(seconds=1) if battle_due else now + timedelta(seconds=60),
        return_at=now + timedelta(seconds=60 if battle_due else 120),
    )


def configure_battle_side_effects(monkeypatch, *, attacker, defender):
    executed_reports: list[int] = []
    dispatches: list[int] = []
    side_effect_lock = threading.Lock()

    monkeypatch.setattr(combat_battle, "_lock_battle_manors", lambda *_args, **_kwargs: (attacker, defender))
    monkeypatch.setattr(combat_battle, "_get_defender_battle_block_reason", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "apply_defender_troop_losses", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_raid_loot_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_prestige_changes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_defeat_protection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_capture_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_apply_salvage_reward", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_send_raid_battle_messages", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(combat_battle, "_dismiss_marching_raids_if_protected", lambda *_args, **_kwargs: None)

    def _fake_execute(locked_run):
        report = BattleReport.objects.create(
            manor=locked_run.attacker,
            opponent_name=locked_run.defender.display_name,
            battle_type="raid",
            attacker_team=[],
            attacker_troops={},
            defender_team=[],
            defender_troops={},
            rounds=[],
            losses={},
            drops={},
            winner="attacker",
            starts_at=timezone.now(),
            completed_at=timezone.now(),
        )
        with side_effect_lock:
            executed_reports.append(report.pk)
        return report

    def _fake_dispatch(locked_run, *, now=None):
        del now
        with side_effect_lock:
            dispatches.append(locked_run.pk)

    monkeypatch.setattr(combat_battle, "_execute_raid_battle", _fake_execute)
    monkeypatch.setattr(combat_battle, "_dispatch_complete_raid_task", _fake_dispatch)
    return executed_reports, dispatches
