"""
战斗数值计算工具模块

提供战斗中的属性解析、技能加成、伤亡概率等纯数值计算函数。
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..combatants import Combatant


# 二项分布采样阈值：小于此值用精确计算，大于等于此值用正态近似
BINOMIAL_EXACT_THRESHOLD = 1000


def binomial_sample(n: int, p: float, rng: random.Random) -> int:
    """
    二项分布采样：n次独立试验，每次成功概率p，返回成功次数。

    小数量用精确计算，大数量用正态分布近似以提高性能。

    Args:
        n: 试验次数
        p: 每次成功概率
        rng: 随机数生成器

    Returns:
        成功次数
    """
    if n <= 0:
        return 0
    if p <= 0:
        return 0
    if p >= 1:
        return n

    if n < BINOMIAL_EXACT_THRESHOLD:
        # 精确计算：逐个判断
        return sum(1 for _ in range(n) if rng.random() < p)
    else:
        # 正态近似：μ = n*p, σ = sqrt(n*p*(1-p))
        mean = n * p
        std = math.sqrt(n * p * (1 - p))
        result = rng.gauss(mean, std)
        # 限制在 [0, n] 范围内
        return max(0, min(n, round(result)))


# 属性映射表
STAT_LOOKUP = {
    "attack": "attack",
    "defense": "defense",
    "force": "force_attr",
    "intellect": "intellect_attr",
    "agility": "agility",
    "luck": "luck",
    "hp": "hp",
}

# 基础伤亡概率
CASUALTY_BASE_PROBABILITY = 0.8


def resolve_stat(combatant: "Combatant", stat: str) -> float:
    """
    解析战斗单位的指定属性值。

    对于小兵单位，返回单兵属性而非总属性，避免技能伤害公式因使用
    总防御（如3000）而产生巨大负数加成。

    Args:
        combatant: 战斗单位
        stat: 属性名称（如 'attack', 'force'）

    Returns:
        属性值（浮点数）
    """
    # 小兵单位：返回单兵属性（用于技能伤害公式计算）
    if getattr(combatant, "kind", "") == "troop":
        if stat == "defense":
            return float(getattr(combatant, "unit_defense", 0))
        if stat == "attack":
            return float(getattr(combatant, "unit_attack", 0))
        if stat == "hp":
            return float(getattr(combatant, "unit_hp", 0))
        # 小兵没有 force/intellect/luck 等属性，返回0
        if stat in ("force", "intellect", "luck", "agility"):
            return 0.0

    attr = STAT_LOOKUP.get(stat)
    if not attr:
        return 0.0
    return float(getattr(combatant, attr, 0))


def calculate_skill_bonus(skill: dict, actor: "Combatant", target: "Combatant") -> int:
    """
    计算技能带来的额外伤害/治疗加成。
    
    支持基于公式计算：base + (ally_stat * coeff) - (enemy_stat * coeff)
    
    Args:
        skill: 技能配置字典
        actor: 施法者
        target: 目标
        
    Returns:
        加成数值（整数）
    """
    formula = skill.get("damage_formula") or {}
    if not formula:
        return int(skill.get("power", 0) * 0.2)

    total = float(formula.get("base", 0))

    # 己方属性加成
    for stat, coeff in (formula.get("ally") or {}).items():
        total += float(coeff) * resolve_stat(actor, stat)

    # 敌方属性减免
    for stat, coeff in (formula.get("enemy") or {}).items():
        total -= float(coeff) * resolve_stat(target, stat)

    return int(total)


def casualty_modifier(team: List["Combatant"], is_winner: bool) -> float:
    """
    计算伤亡概率修正值。
    
    Hook for 科技/道具调整阵亡概率，默认不做变更。
    
    Args:
        team: 队伍列表
        is_winner: 是否胜利方
        
    Returns:
        修正值（浮点数）
    """
    return 0.0


def casualty_probability(team: List["Combatant"], is_winner: bool) -> float:
    """
    计算最终伤亡概率。
    
    Args:
        team: 队伍列表
        is_winner: 是否胜利方
        
    Returns:
        伤亡概率（0.05 ~ 0.95）
    """
    base = CASUALTY_BASE_PROBABILITY
    modifier = casualty_modifier(team, is_winner)
    return max(0.05, min(0.95, base + modifier))


def calculate_team_losses(
    team: List["Combatant"],
    is_winner: bool,
    rng: random.Random,
    side: str = "attacker",
) -> Dict[str, float]:
    """
    计算队伍的战斗损失统计。

    包括：
    - 兵力损失
    - HP损失比例
    - 阵亡名单

    Args:
        team: 队伍列表
        is_winner: 是否胜利方
        rng: 随机数生成器
        side: 阵营 ("attacker" 或 "defender")

    Returns:
        损失统计字典
    """
    total_hp = sum(c.max_hp for c in team) or 1
    remaining_hp = sum(max(0, c.hp) for c in team)
    lost_hp = max(0, total_hp - remaining_hp)
    hp_loss_ratio = lost_hp / total_hp

    # 被击败的护院损失概率：进攻方80%，防守方70%
    defeated_troop_loss_rate = 0.8 if side == "attacker" else 0.7

    total_troops = sum(
        getattr(c, "initial_troop_strength", c.troop_strength)
        for c in team if c.kind == "troop"
    )
    troops_deployed = total_troops
    casualties = []
    total_lost = 0

    for combatant in team:
        if combatant.kind == "troop":
            initial = getattr(combatant, "initial_troop_strength", combatant.troop_strength)
            remaining = max(0, combatant.troop_strength)
            actual_lost = max(0, initial - remaining)

            if actual_lost > 0:
                # 每个被击败的护院单独判断是否损失（使用二项分布采样）
                lost = binomial_sample(actual_lost, defeated_troop_loss_rate, rng)
            else:
                # 护院未被攻击：无损失
                lost = 0

            total_lost += lost
            if initial > 0:
                casualties.append(
                    {
                        "key": combatant.template_key or combatant.name,
                        "label": combatant.name,
                        "lost": lost,
                    }
                )
        else:
            if combatant.hp <= 0:
                casualties.append(
                    {
                        "key": combatant.template_key or combatant.name,
                        "label": combatant.name,
                        "lost": 1,
                    }
                )

    troops_lost = total_lost
    troops_remaining = max(0, troops_deployed - troops_lost) if troops_deployed else 0
    hp_loss_percent = int(hp_loss_ratio * 100)

    return {
        "troops_deployed": troops_deployed,
        "troops_lost": troops_lost,
        "troops_remaining": troops_remaining,
        "troop_loss_rate": defeated_troop_loss_rate,
        "hp_loss_ratio": round(hp_loss_ratio, 3),
        "hp_loss_percent": hp_loss_percent,
        "casualties": casualties,
    }
