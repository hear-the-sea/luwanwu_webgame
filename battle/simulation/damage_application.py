"""
伤害应用逻辑
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .types import _DamageApplication

if TYPE_CHECKING:
    from ..combatants import Combatant


def apply_damage_results(
    actor: "Combatant",
    target: "Combatant",
    damage: int,
    rng: random.Random,
) -> _DamageApplication:
    """
    将伤害应用到目标，并处理命中后结算：
    - 目标 HP/兵力扣减与击杀数计算
    - 技术效果：反伤（剑系）、反击（枪系）
    - 检查攻击者是否被反伤/反击击败

    该函数会直接修改 `actor` 和 `target` 的状态（HP、兵力等）。
    """
    from ..combat_math import (
        calculate_slaughter_multiplier,
        effective_attack_value,
        troop_unit_hp,
    )

    target.hp -= damage
    target_defeated = target.hp <= 0

    display_damage = damage

    # 【护身剑罡】剑系伤害反弹
    reflect_damage = 0
    reflect_kills = 0
    reflect_defeated = False
    reflect_ratio = target.tech_effects.get("damage_reflect", 0)
    if reflect_ratio > 0 and target.troop_class == "jian":
        max_reflect = int(actor.attack * 1.0)
        reflect_damage = min(int(damage * reflect_ratio), max_reflect)
        actor.hp -= reflect_damage

        if actor.kind == "troop":
            per_unit_hp_actor = troop_unit_hp(actor)
            slaughter_mult_reflect = calculate_slaughter_multiplier(target, actor)
            reflect_kills = int(reflect_damage * slaughter_mult_reflect / per_unit_hp_actor)
            reflect_kills = max(0, min(actor.troop_strength, reflect_kills))
            actor.troop_strength = max(0, actor.troop_strength - reflect_kills)
            if actor.troop_strength <= 0:
                reflect_defeated = True
                actor.hp = min(actor.hp, 0)
        else:  # actor.kind == "guest"
            if actor.hp <= 0:
                reflect_kills = 1
                reflect_defeated = True

    # 【反戈一击】枪系反击
    counter_damage = 0
    counter_kills = 0
    counter_defeated = False
    counter_chance = target.tech_effects.get("counter_attack_chance", 0)
    if counter_chance > 0 and target.hp > 0 and rng.random() < counter_chance:
        counter_mult = target.tech_effects.get("counter_attack_damage", 0.30)
        counter_attack_value = effective_attack_value(target, actor)
        counter_damage = int(counter_attack_value * counter_mult)
        actor.hp -= counter_damage

        if actor.kind == "troop":
            per_unit_hp_actor = troop_unit_hp(actor)
            slaughter_mult_counter = calculate_slaughter_multiplier(target, actor)
            counter_kills = int(counter_damage * slaughter_mult_counter / per_unit_hp_actor)
            counter_kills = max(0, min(actor.troop_strength, counter_kills))
            actor.troop_strength = max(0, actor.troop_strength - counter_kills)
            if actor.troop_strength <= 0:
                counter_defeated = True
                actor.hp = min(actor.hp, 0)
        else:  # actor.kind == "guest"
            if actor.hp <= 0:
                counter_kills = 1
                counter_defeated = True

    actor_defeated = False
    if actor.hp <= 0:
        actor.hp = min(actor.hp, 0)
        actor_defeated = True

    kills = 0
    if target.kind == "troop":
        per_unit_hp = troop_unit_hp(target)
        kills = int(damage / per_unit_hp)
        kills = max(0, min(target.troop_strength, kills))
        target.troop_strength = max(0, target.troop_strength - kills)
        if target_defeated or target.troop_strength <= 0:
            target_defeated = True
            target.hp = min(target.hp, 0)
        display_damage = damage
    else:
        kills = 1 if target_defeated else 0

    return _DamageApplication(
        display_damage=display_damage,
        kills=kills,
        target_defeated=target_defeated,
        actor_defeated=actor_defeated,
        reflect_damage=reflect_damage,
        reflect_kills=reflect_kills,
        reflect_defeated=reflect_defeated,
        counter_damage=counter_damage,
        counter_kills=counter_kills,
        counter_defeated=counter_defeated,
    )
