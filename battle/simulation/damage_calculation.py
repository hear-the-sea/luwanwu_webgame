"""
伤害计算逻辑
"""

from __future__ import annotations

import random
from typing import List, Literal, TYPE_CHECKING, overload

from .constants import (
    BASE_CRIT_CHANCE,
    COUNTER_DAMAGE_MULTIPLIER,
    CRIT_DAMAGE_MULTIPLIER,
    DAMAGE_VARIANCE_MAX,
    DAMAGE_VARIANCE_MIN,
    DEFAULT_DEFENSE_CONSTANT,
    GUEST_VS_GUEST_DAMAGE_MULTIPLIER,
    GUEST_VS_GUEST_DEFENSE_CONSTANT,
    GUEST_VS_TROOP_DEFENSE_CONSTANT,
    HARDCAP,
    PREEMPTIVE_DAMAGE_REDUCTION,
    SOFTCAP_THRESHOLD,
    TROOP_COUNTERS,
    TROOP_VS_GUEST_DEFENSE_CONSTANT,
)
from .target_selection import is_ranged_attack
from .types import AttackSkill, _DamageCalculation

if TYPE_CHECKING:
    from ..combatants import Combatant


@overload
def process_status_effects(
    actor: "Combatant",
    target: "Combatant",
    skills: List[AttackSkill],
    rng: random.Random,
    *,
    phase: Literal["damage_penalty"],
    damage: int,
) -> int: ...


@overload
def process_status_effects(
    actor: "Combatant",
    target: "Combatant",
    skills: List[AttackSkill],
    rng: random.Random,
    *,
    phase: Literal["inflict"],
    damage: None = None,
) -> List[str]: ...


def process_status_effects(
    actor: "Combatant",
    target: "Combatant",
    skills: List[AttackSkill],
    rng: random.Random,
    *,
    phase: Literal["damage_penalty", "inflict"],
    damage: int | None = None,
) -> int | List[str]:
    """
    状态效果处理（保持战斗日志与 RNG 调用顺序向后兼容）。

    phase:
    - "damage_penalty": 仅处理攻击者身上的伤害惩罚（如士气低落降低伤害）；不消耗 RNG。
    - "inflict": 处理技能对目标施加的状态；会消耗 RNG（施加状态是概率性的）。

    注意：
    - 为避免改变随机序列，"inflict" 必须在所有命中结算（含反击概率判定）完成后调用。
    """
    from ..skills import apply_skill_statuses
    from ..utils.status_effects import get_damage_penalty

    if phase == "damage_penalty":
        if damage is None:
            raise ValueError("damage_penalty phase requires 'damage'")
        damage_penalty = get_damage_penalty(actor)
        if damage_penalty > 0:
            damage = int(damage * (1 - damage_penalty))
            damage = max(1, damage)
        return damage

    return apply_skill_statuses(skills, target, rng)


def calculate_attack_damage(
    actor: "Combatant",
    target: "Combatant",
    skills: List[AttackSkill],
    rng: random.Random,
    *,
    round_priority: int,
) -> _DamageCalculation:
    """
    计算本次命中对目标造成的最终伤害。

    覆盖内容（与历史实现保持一致的顺序）：
    1) 计算有效攻击
    2) 计算目标防御（按小兵/门客、攻击者类型区分）
    3) 应用武艺技术影响（远程防御、弓近战加成）
    4) 应用五行相克固定倍率
    5) 按战斗双方类型计算防御减伤（含软/硬上限）
    6) 伤害随机波动
    7) 暴击判定
    8) 技能伤害加成
    9) 先手回合调整 + 特定武艺倍率
    10) 双倍打击
    11) 状态惩罚（伤害降低）
    12) 屠戮倍率（门客打小兵）

    该函数不直接修改 actor/target 的血量或兵力，专注于"伤害数值"的计算。
    """
    from ..combat_math import (
        calculate_slaughter_multiplier,
        effective_attack_value,
        effective_defense_value,
    )
    from ..skills import skill_damage_bonus

    attack_value = effective_attack_value(actor, target)

    # 混合防御系统：根据攻击者和目标类型使用不同防御计算
    if target.kind == "troop":
        if actor.kind == "guest":
            defense_value = target.unit_defense
        else:
            defense_value = effective_defense_value(target, actor)
    else:
        defense_value = target.defense

    # === 武艺技术特殊效果 ===

    # 【万宗归流】拳系对远程攻击的防御加成
    if is_ranged_attack(actor, round_priority):
        ranged_def = target.tech_effects.get("ranged_defense", 0)
        if ranged_def > 0:
            defense_value = int(defense_value * (1 + ranged_def))

    # 【短刃杀法】弓箭手近战攻击加成
    if actor.troop_class == "gong" and not is_ranged_attack(actor, round_priority):
        melee_bonus = actor.tech_effects.get("melee_attack_bonus", 0)
        if melee_bonus > 0:
            attack_value = int(attack_value * (1 + melee_bonus))

    # === 五行相克系统（天生属性，自动生效）===
    countered_class = TROOP_COUNTERS.get(actor.troop_class)
    if countered_class and target.troop_class == countered_class:
        attack_value = int(attack_value * COUNTER_DAMAGE_MULTIPLIER)

    # 防御减伤公式：根据战斗双方类型选择不同计算方式
    if target.kind == "troop" and actor.kind == "guest":
        base_reduction = defense_value / (defense_value + GUEST_VS_TROOP_DEFENSE_CONSTANT)
        damage_reduction = min(base_reduction, HARDCAP)
    elif target.kind == "guest" and actor.kind == "guest":
        base_reduction = defense_value / (defense_value + GUEST_VS_GUEST_DEFENSE_CONSTANT)
        if base_reduction > SOFTCAP_THRESHOLD:
            excess = base_reduction - SOFTCAP_THRESHOLD
            damage_reduction = SOFTCAP_THRESHOLD + excess * 0.5
        else:
            damage_reduction = base_reduction
        damage_reduction = min(HARDCAP, damage_reduction)
    elif target.kind == "guest" and actor.kind == "troop":
        base_reduction = defense_value / (defense_value + TROOP_VS_GUEST_DEFENSE_CONSTANT)
        if base_reduction > SOFTCAP_THRESHOLD:
            excess = base_reduction - SOFTCAP_THRESHOLD
            damage_reduction = SOFTCAP_THRESHOLD + excess * 0.5
        else:
            damage_reduction = base_reduction
        damage_reduction = min(HARDCAP, damage_reduction)
    else:
        base_reduction = defense_value / (defense_value + DEFAULT_DEFENSE_CONSTANT)
        if base_reduction > SOFTCAP_THRESHOLD:
            excess = base_reduction - SOFTCAP_THRESHOLD
            damage_reduction = SOFTCAP_THRESHOLD + excess * 0.5
        else:
            damage_reduction = base_reduction
        damage_reduction = min(HARDCAP, damage_reduction)

    attack_multiplier = rng.uniform(DAMAGE_VARIANCE_MIN, DAMAGE_VARIANCE_MAX)

    if target.kind == "troop" and actor.kind == "guest":
        base_damage = attack_value * attack_multiplier * (1 - damage_reduction)
    elif target.kind == "guest" and actor.kind == "guest":
        base_damage = attack_value * attack_multiplier * (1 - damage_reduction)
        base_damage *= GUEST_VS_GUEST_DAMAGE_MULTIPLIER
    elif target.kind == "guest" and actor.kind == "troop":
        base_damage = attack_value * attack_multiplier * (1 - damage_reduction)
    else:
        base_damage = attack_value * attack_multiplier * (1 - damage_reduction)

    crit_chance = BASE_CRIT_CHANCE
    is_crit = rng.random() < crit_chance
    if is_crit:
        base_damage *= CRIT_DAMAGE_MULTIPLIER

    bonus = skill_damage_bonus(skills, actor, target)
    damage = int(base_damage + bonus)
    damage = max(1, damage)

    # 先手伤害调整
    is_preemptive_guest = actor.kind == "guest" and actor.priority == -1
    if is_preemptive_guest:
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

    damage = process_status_effects(actor, target, skills, rng, phase="damage_penalty", damage=damage)

    # 屠戮倍率：门客对小兵的伤害直接乘倍率，保持 HP 与兵力一致
    from ..combat_math import calculate_slaughter_multiplier

    if target.kind == "troop":
        slaughter_mult = calculate_slaughter_multiplier(actor, target)
        if slaughter_mult != 1.0:
            damage = int(damage * slaughter_mult)
            damage = max(1, damage)

    return _DamageCalculation(damage=damage, is_crit=is_crit, is_double_strike=is_double_strike)
