"""
战斗流程控制
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from django.utils import timezone

from .attack_execution import perform_attack
from .constants import MAX_ALLOWED_PRIORITY, MIN_ALLOWED_PRIORITY
from .turn_order import determine_turn_order
from .utils import alive, roll_loot, summarize_losses

if TYPE_CHECKING:
    from ..combatants import BattleSimulationResult, Combatant

logger = logging.getLogger(__name__)


def resolve_priority_phases(
    attacker_team: List["Combatant"],
    defender_team: List["Combatant"],
    rng: random.Random,
) -> Tuple[List[Dict[str, Any]], int]:
    from ..status_manager import prepare_combatants_for_round, try_trigger_battle_heal_on_action
    from ..utils.status_effects import handle_pre_action_status

    participants = alive(attacker_team) + alive(defender_team)
    priority_values = sorted({c.priority for c in participants if c.priority < 0})
    if not priority_values:
        return [], 1
    rounds: List[Dict[str, Any]] = []
    next_round_no = 1
    min_priority = min(priority_values)

    # 安全修复：验证优先级上下限，防止异常优先级值导致过多阶段循环
    if min_priority < MIN_ALLOWED_PRIORITY:
        logger.warning(
            "Priority value %d exceeds minimum allowed %d, clamping",
            min_priority,
            MIN_ALLOWED_PRIORITY,
        )
        min_priority = MIN_ALLOWED_PRIORITY

    # 安全修复：同时检查优先级上限
    if min_priority > MAX_ALLOWED_PRIORITY:
        logger.warning(
            "Priority value %d exceeds maximum allowed %d, clamping",
            min_priority,
            MAX_ALLOWED_PRIORITY,
        )
        min_priority = MAX_ALLOWED_PRIORITY

    staged_priorities = list(range(min_priority, 0))
    for priority in staged_priorities:
        events: List[Dict[str, Any]] = []
        prepare_combatants_for_round(attacker_team, defender_team, next_round_no, promote_pending=True)
        phase_attackers = [
            actor for actor in determine_turn_order(attacker_team, defender_team, rng)
            if actor.priority <= priority
        ]
        for actor in phase_attackers:
            if actor.hp <= 0:
                continue
            # 先判定控制状态（眩晕/冻结等）
            if handle_pre_action_status(actor, events):
                continue
            # 未被控制的单位，在行动前尝试触发五气朝元（拳类武艺科技）
            heal_event = try_trigger_battle_heal_on_action(actor, rng)
            if heal_event:
                heal_event["order"] = len(events) + 1
                heal_event["type"] = "heal"
                events.append(heal_event)
            event = perform_attack(actor, attacker_team, defender_team, rng, round_priority=priority)
            if event:
                event["order"] = len(events) + 1
                event["priority_phase"] = priority
                event["preemptive"] = True
                events.append(event)
        waiting_units = [
            unit for unit in alive(attacker_team) + alive(defender_team)
            if unit.priority > priority and unit.hp > 0
        ]
        for unit in waiting_units:
            events.append(
                {
                    "actor": unit.name,
                    "side": unit.side,
                    "status": "charging",
                    "message": "冲锋中",
                    "order": len(events) + 1,
                }
            )
        rounds.append({"round": next_round_no, "events": events, "priority": priority})
        next_round_no += 1
        if not alive(attacker_team) or not alive(defender_team):
            break
    return rounds, next_round_no


def simulate_battle(
    attacker_units: List["Combatant"],
    defender_units: List["Combatant"],
    rng: random.Random,
    seed: int,
    travel_seconds: int | None,
    config: dict,
    drop_table: Dict[str, Any] | None = None,
    max_rounds: int | None = None,
) -> "BattleSimulationResult":
    from ..combatants import BattleSimulationResult
    from ..constants import MAX_ROUNDS
    from ..status_manager import prepare_combatants_for_round, try_trigger_battle_heal_on_action
    from ..utils.status_effects import handle_pre_action_status

    if max_rounds is None:
        max_rounds = MAX_ROUNDS

    # 安全修复：验证回合数范围，防止负数和过大值导致异常
    max_rounds = max(1, min(max_rounds, MAX_ROUNDS * 2))
    rounds: List[Dict[str, Any]] = []
    priority_rounds, next_round_start = resolve_priority_phases(attacker_units, defender_units, rng)
    rounds.extend(priority_rounds)
    round_no = next_round_start
    remaining_rounds = max_rounds
    while remaining_rounds > 0 and alive(attacker_units) and alive(defender_units):
        prepare_combatants_for_round(attacker_units, defender_units, round_no, promote_pending=True)
        events: List[Dict[str, Any]] = []
        for actor in determine_turn_order(attacker_units, defender_units, rng):
            if actor.hp <= 0:
                continue
            # 先判定控制状态（眩晕/冻结等）
            if handle_pre_action_status(actor, events):
                continue
            # 未被控制的单位，在行动前尝试触发五气朝元（拳类武艺科技）
            heal_event = try_trigger_battle_heal_on_action(actor, rng)
            if heal_event:
                heal_event["order"] = len(events) + 1
                heal_event["type"] = "heal"
                events.append(heal_event)
            event = perform_attack(actor, attacker_units, defender_units, rng, round_priority=0)
            if event:
                event["order"] = len(events) + 1
                events.append(event)
            if not alive(defender_units) or not alive(attacker_units):
                break
        rounds.append({"round": round_no, "events": events})
        round_no += 1
        remaining_rounds -= 1

    # 胜负判定：攻击方必须消灭所有敌方单位才算获胜
    defender_alive_units = alive(defender_units)
    attacker_alive_units = alive(attacker_units)

    if not defender_alive_units:
        # 防守方全灭 → 攻击方获胜
        winner = "attacker"
    elif not attacker_alive_units:
        # 攻击方全灭 → 防守方获胜
        winner = "defender"
    else:
        # 双方都有存活 → 回合结束，防守方守住 → 防守方获胜
        winner = "defender"

    now = timezone.now()
    travel = timedelta(seconds=travel_seconds if travel_seconds is not None else 5)
    starts_at = now + travel
    completed_at = starts_at

    losses = summarize_losses(attacker_units, defender_units, winner, rng)
    drops: Dict[str, int] = {}
    if winner == "attacker":
        if drop_table is not None:
            from common.utils.loot import resolve_drop_rewards

            drops = resolve_drop_rewards(drop_table, rng)
        else:
            drops = roll_loot(config, rng)

    return BattleSimulationResult(
        rounds=rounds,
        winner=winner,
        losses=losses,
        drops=drops,
        seed=seed,
        starts_at=starts_at,
        completed_at=completed_at,
    )
