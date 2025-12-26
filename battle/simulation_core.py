from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from .combatants import BattleSimulationResult, Combatant
from .combat_math import (
    calculate_slaughter_multiplier,
    effective_attack_value,
    effective_defense_value,
    troop_unit_hp,
)
from .constants import MAX_ROUNDS
from .skills import apply_skill_statuses, skill_damage_bonus, trigger_skills
from .status_manager import prepare_combatants_for_round, try_trigger_battle_heal_on_action
from .utils.battle_calculator import calculate_team_losses
from .utils.status_effects import handle_pre_action_status, get_damage_penalty

logger = logging.getLogger(__name__)

# ============ 目标选择配置 ============

# 优先目标权重：60% 概率选择优先目标，40% 保留随机性
# 这个权重经过平衡性考虑：既能遏制炮灰策略，又保留足够的不确定性
PRIORITY_TARGET_WEIGHT = 0.60

# ============ 五行相克配置 ============

# 五行相克关系：护院攻击时优先选择克制兵种
# 克制关系：刀→剑→拳→弓→枪→刀
TROOP_COUNTERS: Dict[str, str] = {
    "dao": "jian",    # 刀克剑
    "jian": "quan",   # 剑克拳
    "quan": "gong",   # 拳克弓
    "gong": "qiang",  # 弓克枪
    "qiang": "dao",   # 枪克刀
}

# 克制伤害倍率：攻击被克制目标时的额外伤害
COUNTER_DAMAGE_MULTIPLIER = 1.5

# ============ 防御减伤常数配置 ============

# 标准防御常数（用于小兵战斗）
# 公式：damage_reduction = defense / (defense + constant)
# 值越大，相同防御下减伤越低
DEFAULT_DEFENSE_CONSTANT = 120

# 门客对门客防御常数（软上限公式）
# 公式：base = defense / (defense + 600)，超过50%后收益减半，上限75%
# 设计理由：
# - 常数600让防御属性更有价值（313防御34%减伤，803防御54%减伤）
# - 防御收益从+1.2回合提升到+2.2回合，装备有意义
# - 配合15x倍率保持合理战斗节奏（约5-7回合击杀）
GUEST_VS_GUEST_DEFENSE_CONSTANT = 600

# 小兵对门客防御常数（软上限公式的基础常数）
# 公式：base = defense / (defense + 200)，超过50%后收益减半，上限75%
# 效果：低防御有效，高防御收益递减，装备提升不会导致极端减伤
TROOP_VS_GUEST_DEFENSE_CONSTANT = 200

# 软上限阈值：超过此值后，额外减伤收益减半
SOFTCAP_THRESHOLD = 0.50

# 硬上限：减伤不会超过此值（适用于小兵打门客、小兵打小兵）
HARDCAP = 0.75

# 门客对门客额外伤害倍率
# 设计理由：
# - 配合常数600的软上限公式（34-54%减伤）
# - 15x倍率确保战斗在合理回合内结束
# - 313防御约5.2回合击杀，803防御约7.3回合击杀
GUEST_VS_GUEST_DAMAGE_MULTIPLIER = 15.0

# ============ 战斗数值常数 ============

# 基础暴击率（敏捷不再影响暴击）
BASE_CRIT_CHANCE = 0.05

# 暴击伤害倍率
CRIT_DAMAGE_MULTIPLIER = 1.5

# 先手伤害衰减比例（门客先手时的伤害降低）
PREEMPTIVE_DAMAGE_REDUCTION = 0.8

# 伤害随机波动范围
DAMAGE_VARIANCE_MIN = 0.9
DAMAGE_VARIANCE_MAX = 1.1

# 门客对小兵的防御减伤常量（渐进公式）
# 公式：reduction = defense / (defense + GUEST_VS_TROOP_DEFENSE_CONSTANT)
# K=50 设计效果（中等强度）：
#   - 防御4: 7.4% 减伤
#   - 防御6: 10.7% 减伤
#   - 防御10: 16.7% 减伤
#   - 防御13: 20.6% 减伤
# 高防兵种（枪系）有明显战略价值，低防兵种差距也不会太大
GUEST_VS_TROOP_DEFENSE_CONSTANT = 50

# ============ 优先级阶段配置 ============

# 允许的最小优先级值（防止配置错误导致无限循环）
MIN_ALLOWED_PRIORITY = -10

# 允许的最大优先级值
MAX_ALLOWED_PRIORITY = 10


def calculate_crit_chance(actor: Combatant) -> float:
    """
    计算暴击率（敏捷不再影响暴击）
    固定基础暴击率
    """
    return BASE_CRIT_CHANCE


def calculate_dodge_chance(target: Combatant) -> float:
    """
    闪避率已移除（敏捷不再影响闪避）
    """
    return 0.0


def build_rng(seed: int | None = None) -> Tuple[int, random.Random]:
    final_seed = seed if seed is not None else random.randint(1, 999_999_999)
    return final_seed, random.Random(final_seed)


def summarize_losses(
    attacker_team: List[Combatant],
    defender_team: List[Combatant],
    winner: str,
    rng: random.Random,
) -> Dict[str, dict]:
    return {
        "attacker": calculate_team_losses(attacker_team, winner == "attacker", rng, side="attacker"),
        "defender": calculate_team_losses(defender_team, winner == "defender", rng, side="defender"),
    }


def roll_loot(config: dict, rng: random.Random) -> Dict[str, int]:
    loot_pool = config.get("loot_pool") or {}
    if not loot_pool:
        return {}
    resources = list(loot_pool.items())
    rng.shuffle(resources)
    take_count = rng.randint(1, len(resources))
    drops: Dict[str, int] = {}
    for resource, base_amount in resources[:take_count]:
        portion = rng.uniform(0.4, 0.85)
        amount = int(base_amount * portion)
        if amount > 0:
            drops[resource] = amount
    return drops


def alive(team: List[Combatant]) -> List[Combatant]:
    """
    判断战斗单位是否存活

    规则：
    - 门客：hp > 0
    - 护院：hp > 0 且 troop_strength > 0
    """
    result = []
    for c in team:
        if c.hp <= 0:
            continue
        # 护院需要额外检查兵力
        if c.kind == "troop" and c.troop_strength <= 0:
            continue
        result.append(c)
    return result


def determine_turn_order(
    attacker_team: List[Combatant],
    defender_team: List[Combatant],
    rng: random.Random,
) -> List[Combatant]:
    participants = alive(attacker_team) + alive(defender_team)
    if not participants:
        return []
    weighted: List[Tuple[float, float, Combatant]] = []
    for combatant in participants:
        initiative = combatant.agility + rng.uniform(0, 5)
        weighted.append((initiative, rng.random(), combatant))
    weighted.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in weighted]


def is_ranged_attack(actor: Combatant, round_priority: int) -> bool:
    """判断是否为远程攻击（弓箭手在先攻/先锋回合视为远程攻击）"""
    if actor.troop_class != "gong":
        return False
    # 弓箭手在先锋回合(-2)和先攻回合(-1)视为远程攻击
    return round_priority < 0


def select_target_with_priority(
    actor: Combatant,
    opponents: List[Combatant],
    rng: random.Random
) -> Combatant:
    """
    加权概率选择攻击目标。

    护院优先攻击克制的敌方兵种（五行相克），门客优先攻击敌方门客。
    通过 PRIORITY_TARGET_WEIGHT 权重平衡策略性和随机性。

    Args:
        actor: 攻击者
        opponents: 可选敌方目标列表（已排除已阵亡单位）
        rng: 随机数生成器

    Returns:
        选中的攻击目标

    Examples:
        >>> # 刀兵有70%概率优先攻击剑兵
        >>> # 门客有70%概率优先攻击敌方门客
        >>> # 30%概率随机选择，增加战斗不确定性
    """
    priority_targets: List[Combatant] = []

    # 护院：优先攻击克制的兵种
    if actor.kind == "troop":
        counter_class = TROOP_COUNTERS.get(actor.troop_class)
        if counter_class:
            priority_targets = [
                unit for unit in opponents
                if unit.troop_class == counter_class
            ]

    # 门客：优先攻击敌方门客
    elif actor.kind == "guest":
        priority_targets = [
            unit for unit in opponents
            if unit.kind == "guest"
        ]

    # 加权概率判定
    if priority_targets and rng.random() < PRIORITY_TARGET_WEIGHT:
        return rng.choice(priority_targets)

    # 无优先目标或随机判定：完全随机选择
    return rng.choice(opponents)


def perform_attack(
    actor: Combatant,
    attacker_team: List[Combatant],
    defender_team: List[Combatant],
    rng: random.Random,
    round_priority: int = 0,
) -> Dict[str, Any] | None:
    if actor.side == "attacker":
        opponents = alive(defender_team)
    else:
        opponents = alive(attacker_team)

    if not opponents:
        actor.has_acted_this_round = True
        actor.last_round_acted = actor.current_round
        return None

    # 加权概率选择目标（护院优先克制兵种，门客优先门客）
    target = select_target_with_priority(actor, opponents, rng)
    skills = trigger_skills(actor, rng)
    multi_targets = max(1, max(int(skill.get("targets", 1)) for skill in skills) if skills else 1)
    engaged_targets = [target]
    available_opponents = [unit for unit in opponents if unit is not target]
    rng.shuffle(available_opponents)
    for extra in available_opponents[: multi_targets - 1]:
        engaged_targets.append(extra)

    action_logs: List[Dict[str, Any]] = []
    actor_defeated = False
    for idx, current_target in enumerate(engaged_targets):
        # 1. 闪避判定（优先）
        dodge_chance = calculate_dodge_chance(current_target)
        if rng.random() < dodge_chance:
            entry = {
                "actor": actor.name,
                "target": current_target.name,
                "damage": 0,
                "is_dodge": True,
                "is_crit": False,
                "side": actor.side,
                "skills": [skill["name"] for skill in skills],
                "agility": actor.agility,
                "kind": actor.kind,
                "priority": actor.priority,
                "status_inflicted": [],
                "index": idx,
                "kills": 0,
                "target_defeated": False,
            }
            action_logs.append(entry)
            continue

        # 2. 计算基础伤害
        attack_value = effective_attack_value(actor, current_target)

        # 混合防御系统：根据攻击者和目标类型使用不同防御计算
        if current_target.kind == "troop":
            # 小兵被攻击时，根据攻击者类型选择防御计算方式
            if actor.kind == "guest":
                # 门客打小兵：使用单兵防御（简单直观，配合屠戮倍率）
                defense_value = current_target.unit_defense
            else:
                # 小兵打小兵：使用缩放防御（避免大规模互殴失衡）
                defense_value = effective_defense_value(current_target, actor)
        else:
            # 门客：直接使用防御属性
            defense_value = current_target.defense

        # === 武艺技术特殊效果 ===

        # 【万宗归流】拳系对远程攻击的防御加成
        if is_ranged_attack(actor, round_priority):
            ranged_def = current_target.tech_effects.get("ranged_defense", 0)
            if ranged_def > 0:
                defense_value = int(defense_value * (1 + ranged_def))

        # 【短刃杀法】弓箭手近战攻击加成
        if actor.troop_class == "gong" and not is_ranged_attack(actor, round_priority):
            melee_bonus = actor.tech_effects.get("melee_attack_bonus", 0)
            if melee_bonus > 0:
                attack_value = int(attack_value * (1 + melee_bonus))

        # === 五行相克系统（天生属性，自动生效）===
        # 克制关系查表，固定伤害加成，无需研究科技
        countered_class = TROOP_COUNTERS.get(actor.troop_class)
        if countered_class and current_target.troop_class == countered_class:
            attack_value = int(attack_value * COUNTER_DAMAGE_MULTIPLIER)

        # 防御减伤公式：根据战斗双方类型选择不同计算方式
        if current_target.kind == "troop" and actor.kind == "guest":
            # 门客打小兵：渐进公式（与其他战斗类型一致）
            # 公式：reduction = defense / (defense + 25)
            # 让高防兵种（枪系）有明显战略价值，硬上限75%
            base_reduction = defense_value / (defense_value + GUEST_VS_TROOP_DEFENSE_CONSTANT)
            damage_reduction = min(base_reduction, HARDCAP)
        elif current_target.kind == "guest" and actor.kind == "guest":
            # 门客打门客：软上限公式
            # 基础减伤 = defense / (defense + 600)
            # 超过50%后收益减半，硬上限75%
            base_reduction = defense_value / (defense_value + GUEST_VS_GUEST_DEFENSE_CONSTANT)
            if base_reduction > SOFTCAP_THRESHOLD:
                excess = base_reduction - SOFTCAP_THRESHOLD
                damage_reduction = SOFTCAP_THRESHOLD + excess * 0.5
            else:
                damage_reduction = base_reduction
            damage_reduction = min(HARDCAP, damage_reduction)
        elif current_target.kind == "guest" and actor.kind == "troop":
            # 小兵打门客：软上限公式
            # 基础减伤 = defense / (defense + 200)
            # 超过50%后收益减半，硬上限75%
            base_reduction = defense_value / (defense_value + TROOP_VS_GUEST_DEFENSE_CONSTANT)
            if base_reduction > SOFTCAP_THRESHOLD:
                excess = base_reduction - SOFTCAP_THRESHOLD
                damage_reduction = SOFTCAP_THRESHOLD + excess * 0.5
            else:
                damage_reduction = base_reduction
            damage_reduction = min(HARDCAP, damage_reduction)
        else:
            # 小兵打小兵：软上限公式（与小兵打门客一致）
            # 基础减伤 = defense / (defense + 120)
            # 超过50%后收益减半，硬上限75%
            base_reduction = defense_value / (defense_value + DEFAULT_DEFENSE_CONSTANT)
            if base_reduction > SOFTCAP_THRESHOLD:
                excess = base_reduction - SOFTCAP_THRESHOLD
                damage_reduction = SOFTCAP_THRESHOLD + excess * 0.5
            else:
                damage_reduction = base_reduction
            damage_reduction = min(HARDCAP, damage_reduction)

        # 随机波动
        attack_multiplier = rng.uniform(DAMAGE_VARIANCE_MIN, DAMAGE_VARIANCE_MAX)

        # 根据减伤类型应用不同的伤害计算
        if current_target.kind == "troop" and actor.kind == "guest":
            # 门客打小兵：直接应用减伤
            base_damage = attack_value * attack_multiplier * (1 - damage_reduction)
        elif current_target.kind == "guest" and actor.kind == "guest":
            # 门客打门客：应用额外伤害倍率以确保合理战斗效率
            base_damage = attack_value * attack_multiplier * (1 - damage_reduction)
            base_damage *= GUEST_VS_GUEST_DAMAGE_MULTIPLIER
        elif current_target.kind == "guest" and actor.kind == "troop":
            # 小兵打门客：直接应用减伤（使用专用常数TROOP_VS_GUEST_DEFENSE_CONSTANT）
            base_damage = attack_value * attack_multiplier * (1 - damage_reduction)
        else:
            # 小兵打小兵：直接应用减伤（使用软上限公式，无需额外系数）
            base_damage = attack_value * attack_multiplier * (1 - damage_reduction)

        # 3. 暴击判定
        crit_chance = calculate_crit_chance(actor)
        is_crit = rng.random() < crit_chance
        if is_crit:
            base_damage *= CRIT_DAMAGE_MULTIPLIER

        # 4. 技能加成
        bonus = skill_damage_bonus(skills, actor, current_target)
        damage = int(base_damage + bonus)
        damage = max(1, damage)

        # 5. 先手伤害调整
        is_preemptive_guest = actor.kind == "guest" and actor.priority == -1
        if is_preemptive_guest:
            # 门客先手伤害降低
            damage = int(damage * PREEMPTIVE_DAMAGE_REDUCTION)
            damage = max(1, damage)

        # 【驭剑之术】剑系先攻回合伤害倍率
        if actor.troop_class == "jian" and round_priority == -1:
            preempt_mult = actor.tech_effects.get("preemptive_damage", 0)
            if preempt_mult > 0:
                damage = int(damage * preempt_mult)
                damage = max(1, damage)

        # 【凤舞九天】弓箭先锋回合伤害倍率
        if actor.troop_class == "gong" and round_priority == -2:
            extra_range_mult = actor.tech_effects.get("extra_range_damage", 0)
            if extra_range_mult > 0:
                damage = int(damage * extra_range_mult)
                damage = max(1, damage)

        # 【狂狼必杀】刀系双倍打击
        is_double_strike = False
        double_strike_chance = actor.tech_effects.get("double_strike_chance", 0)
        if double_strike_chance > 0 and rng.random() < double_strike_chance:
            damage *= 2
            is_double_strike = True

        # 6. 状态效果伤害惩罚（如士气低落降低30%伤害）
        damage_penalty = get_damage_penalty(actor)
        if damage_penalty > 0:
            damage = int(damage * (1 - damage_penalty))
            damage = max(1, damage)

        # 6.5 屠戮倍率：门客对小兵的伤害直接乘倍率，保持 HP 与兵力一致
        # 注意：只在门客攻击小兵时生效，小兵互殴/门客互殴不受影响
        if current_target.kind == "troop":
            slaughter_mult = calculate_slaughter_multiplier(actor, current_target)
            if slaughter_mult != 1.0:
                damage = int(damage * slaughter_mult)
                damage = max(1, damage)

        # 造成伤害（此处的 damage 为最终结算伤害，已包含屠戮倍率）
        current_target.hp -= damage
        target_defeated = current_target.hp <= 0
        kills = 0

        # 战报显示伤害：对小兵显示实际结算伤害（已包含屠戮倍率）
        display_damage = damage

        # 【护身剑罡】剑系伤害反弹
        reflect_damage = 0
        reflect_kills = 0
        reflect_defeated = False
        reflect_ratio = current_target.tech_effects.get("damage_reflect", 0)
        if reflect_ratio > 0 and current_target.troop_class == "jian":
            # 计算反弹伤害，上限为攻击者攻击力的1倍
            # 设计理由：基于攻击力的上限更稳定，避免前期血量高时反弹无上限
            # 同时防止双倍打击/暴击被过度反弹导致自杀
            max_reflect = int(actor.attack * 1.0)
            reflect_damage = min(int(damage * reflect_ratio), max_reflect)
            actor.hp -= reflect_damage

            # 计算反弹击杀数
            if actor.kind == "troop":
                per_unit_hp_actor = troop_unit_hp(actor)
                slaughter_mult_reflect = calculate_slaughter_multiplier(current_target, actor)
                reflect_kills = int(reflect_damage * slaughter_mult_reflect / per_unit_hp_actor)
                reflect_kills = max(0, min(actor.troop_strength, reflect_kills))
                actor.troop_strength = max(0, actor.troop_strength - reflect_kills)
                if actor.troop_strength <= 0:
                    reflect_defeated = True
                    actor.hp = min(actor.hp, 0)
            else:  # actor.kind == "guest"
                # 门客被反弹击败
                if actor.hp <= 0:
                    reflect_kills = 1
                    reflect_defeated = True

        # 【反戈一击】枪系反击
        counter_damage = 0
        counter_kills = 0
        counter_defeated = False
        counter_chance = current_target.tech_effects.get("counter_attack_chance", 0)
        if counter_chance > 0 and current_target.hp > 0 and rng.random() < counter_chance:
            counter_mult = current_target.tech_effects.get("counter_attack_damage", 0.30)
            counter_attack_value = effective_attack_value(current_target, actor)
            counter_damage = int(counter_attack_value * counter_mult)
            actor.hp -= counter_damage

            # 计算反击击杀数
            if actor.kind == "troop":
                per_unit_hp_actor = troop_unit_hp(actor)
                slaughter_mult_counter = calculate_slaughter_multiplier(current_target, actor)
                counter_kills = int(counter_damage * slaughter_mult_counter / per_unit_hp_actor)
                counter_kills = max(0, min(actor.troop_strength, counter_kills))
                actor.troop_strength = max(0, actor.troop_strength - counter_kills)
                if actor.troop_strength <= 0:
                    counter_defeated = True
                    actor.hp = min(actor.hp, 0)
            else:  # actor.kind == "guest"
                # 门客被反击击败
                if actor.hp <= 0:
                    counter_kills = 1
                    counter_defeated = True

        # 检查攻击者是否被反伤/反击杀死
        if actor.hp <= 0:
            actor.hp = min(actor.hp, 0)
            actor_defeated = True

        if current_target.kind == "troop":
            per_unit_hp = troop_unit_hp(current_target)

            # damage 已包含屠戮倍率，击杀按最终伤害换算即可
            kills = int(damage / per_unit_hp)

            kills = max(0, min(current_target.troop_strength, kills))
            current_target.troop_strength = max(0, current_target.troop_strength - kills)
            if target_defeated or current_target.troop_strength <= 0:
                target_defeated = True
                current_target.hp = min(current_target.hp, 0)

            # 战报显示真实伤害（不转换为等效伤害）
            # 修复：直接显示实际造成的伤害，不要用 kills * per_unit_hp
            # 例如：造成2395伤害，击杀184人（单位HP=13）
            #      显示：2395伤害，而不是 184*13=2392
            display_damage = damage
        else:
            kills = 1 if target_defeated else 0

        entry = {
            "actor": actor.name,
            "target": current_target.name,
            "damage": display_damage,  # 显示等效伤害（小兵=击杀数×单位HP，门客=实际伤害）
            "is_crit": is_crit,
            "is_dodge": False,
            "side": actor.side,
            "skills": [skill["name"] for skill in skills],
            "agility": actor.agility,
            "kind": actor.kind,
            "priority": actor.priority,
            "status_inflicted": [],
            "index": idx,
            "kills": kills,
            "target_defeated": target_defeated,
            # 武艺技术特殊效果记录
            "is_double_strike": is_double_strike,
            "reflect_damage": reflect_damage,
            "reflect_kills": reflect_kills,
            "reflect_defeated": reflect_defeated,
            "counter_damage": counter_damage,
            "counter_kills": counter_kills,
            "counter_defeated": counter_defeated,
            "attack_type": "ranged" if is_ranged_attack(actor, round_priority) else "melee",
            "actor_defeated": actor_defeated,
        }
        entry["status_inflicted"] = apply_skill_statuses(skills, current_target, rng)
        action_logs.append(entry)

        # 如果攻击者被反伤/反击杀死，停止继续攻击其他目标
        if actor_defeated:
            break

    actor.has_acted_this_round = True
    actor.last_round_acted = actor.current_round

    primary = action_logs[0]
    primary["additional_targets"] = action_logs[1:]
    return primary


def resolve_priority_phases(
    attacker_team: List[Combatant],
    defender_team: List[Combatant],
    rng: random.Random,
) -> Tuple[List[Dict[str, Any]], int]:
    participants = alive(attacker_team) + alive(defender_team)
    priority_values = sorted({c.priority for c in participants if c.priority < 0})
    if not priority_values:
        return [], 1
    rounds: List[Dict[str, Any]] = []
    next_round_no = 1
    min_priority = min(priority_values)

    # 防止异常优先级值导致过多阶段循环
    if min_priority < MIN_ALLOWED_PRIORITY:
        logger.warning(
            "Priority value %d exceeds minimum allowed %d, clamping",
            min_priority,
            MIN_ALLOWED_PRIORITY,
        )
        min_priority = MIN_ALLOWED_PRIORITY

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
    attacker_units: List[Combatant],
    defender_units: List[Combatant],
    rng: random.Random,
    seed: int,
    travel_seconds: int | None,
    config: dict,
    drop_table: Dict[str, Any] | None = None,
    max_rounds: int = MAX_ROUNDS,
) -> BattleSimulationResult:
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
            from gameplay.services import resolve_drop_rewards

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
