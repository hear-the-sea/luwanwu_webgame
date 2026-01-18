from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

from django.db import DatabaseError
from django.utils import timezone

from guests.models import Guest, GuestTemplate, Skill, SkillKind

from .constants import MAX_SQUAD
from .troops import default_troop_loadout, load_troop_templates

logger = logging.getLogger(__name__)

# ============ 模板缓存 ============

@lru_cache(maxsize=1)
def _get_all_guest_templates() -> Dict[str, GuestTemplate]:
    """缓存所有门客模板（按 key 索引）"""
    return {t.key: t for t in GuestTemplate.objects.all()}


def clear_guest_template_cache() -> None:
    """清除门客模板缓存（模板变更时调用）"""
    _get_all_guest_templates.cache_clear()

# ============ 门客战斗常量 ============

# 默认敏捷值（当门客无敏捷属性时使用）
DEFAULT_GUEST_AGILITY = 80

# 智力转换速度的除数（intellect / divisor = 速度加成）
INTELLECT_TO_SPEED_DIVISOR = 10

# 最小速度加成下限
MIN_SPEED_BONUS = 5

# 默认幸运值
DEFAULT_LUCK = 50

# 先锋比例（敏捷前X%的门客获得先手）
VANGUARD_RATIO = 0.25


@dataclass(slots=True)
class BattleSimulationResult:
    rounds: List[Dict[str, Any]]
    winner: str
    losses: Dict[str, dict]
    drops: Dict[str, int]
    seed: int
    starts_at: timezone.datetime
    completed_at: timezone.datetime


@dataclass(slots=True)
class Combatant:
    name: str
    attack: int
    defense: int
    hp: int
    max_hp: int
    side: str
    rarity: str
    luck: int
    agility: int
    priority: int
    kind: str
    troop_strength: int
    initial_troop_strength: int = 0
    initial_hp: int = 0  # 战斗开始时的HP，用于计算本场损失
    unit_attack: int = 0
    unit_defense: int = 0
    unit_hp: int = 0
    skills: list = field(default_factory=list)
    template_key: str | None = None
    force_attr: int = 0
    intellect_attr: int = 0
    defense_attr: int = 0
    guest_id: int | None = None
    level: int = 1  # 门客等级，用于屠戮倍率和等级减伤计算
    status_effects: Dict[str, Dict[str, int]] = field(default_factory=dict)
    has_acted_this_round: bool = False
    current_round: int = 0
    last_round_acted: int = 0
    # 兵种类别（dao/qiang/jian/quan/gong/scout）
    troop_class: str = ""
    # 武艺技术特殊效果参数
    tech_effects: Dict[str, float] = field(default_factory=dict)


def serialize_skills(guest: Guest, override_skill_keys: Optional[List[str]] = None) -> List[dict]:
    """
    序列化门客技能为战斗系统可用的格式。

    Args:
        guest: 门客实例
        override_skill_keys: 可选的技能key列表，用于覆盖门客原有技能（全局任务临时技能）

    Returns:
        技能字典列表

    逻辑：
        - 优先级1：门客对象的 _override_skills 属性（单独配置的技能）
        - 优先级2：参数 override_skill_keys（全局任务临时技能）
        - 优先级3：guest.skills（玩家门客）
        - 优先级4：template.initial_skills（AI门客）
    """
    data: List[dict] = []

    # 检查门客是否有单独配置的技能覆盖（优先级最高）
    guest_override_skills = getattr(guest, "_override_skills", None)
    effective_override = guest_override_skills if guest_override_skills is not None else override_skill_keys

    # 情况0：任务临时技能覆盖（优先级最高）
    if effective_override:
        try:
            override_keys = [effective_override] if isinstance(effective_override, str) else list(effective_override)
        except TypeError:
            logger.warning(
                "Invalid override skills type; falling back to default skills",
                extra={
                    "guest_id": getattr(guest, "pk", None),
                    "override_skills_type": type(effective_override).__name__,
                },
            )
            override_keys = []

        override_keys = [str(key) for key in override_keys if key]
        if override_keys:
            try:
                skills = Skill.objects.filter(key__in=override_keys)
                for skill in skills:
                    data.append(
                        {
                            "key": skill.key,
                            "name": skill.name,
                            "power": skill.base_power,
                            "probability": skill.base_probability,
                            "kind": getattr(skill, "kind", SkillKind.ACTIVE),
                            "status_effect": getattr(skill, "status_effect", ""),
                            "status_probability": getattr(skill, "status_probability", 0.0),
                            "status_duration": getattr(skill, "status_duration", 1),
                            "damage_formula": getattr(skill, "damage_formula", {}),
                            "targets": getattr(skill, "targets", 1),
                        }
                    )
                return data  # 直接返回，不再获取原有技能
            except DatabaseError:
                # 获取临时技能失败，继续使用原有技能
                logger.warning(
                    "Failed to load override skills for guest; falling back to default skills",
                    extra={
                        "guest_id": getattr(guest, "pk", None),
                        "override_skills_count": len(override_keys),
                    },
                    exc_info=True,
                )

    # 情况1：已保存的门客（玩家门客），从 guest.skills 获取
    if getattr(guest, "pk", None) is not None:
        if hasattr(guest, "skills"):
            try:
                for skill in guest.skills.all():
                    data.append(
                        {
                            "key": skill.key,
                            "name": skill.name,
                            "power": skill.base_power,
                            "probability": skill.base_probability,
                            "kind": getattr(skill, "kind", SkillKind.ACTIVE),
                            "status_effect": getattr(skill, "status_effect", ""),
                            "status_probability": getattr(skill, "status_probability", 0.0),
                            "status_duration": getattr(skill, "status_duration", 1),
                            "damage_formula": getattr(skill, "damage_formula", {}),
                            "targets": getattr(skill, "targets", 1),
                        }
                    )
            except ValueError:
                # unsaved object with m2m: ignore
                pass

    # 情况2：未保存的门客（AI门客），从 template.initial_skills 获取
    else:
        template = getattr(guest, "template", None)
        if template and hasattr(template, "initial_skills"):
            try:
                for skill in template.initial_skills.all():
                    data.append(
                        {
                            "key": skill.key,
                            "name": skill.name,
                            "power": skill.base_power,
                            "probability": skill.base_probability,
                            "kind": getattr(skill, "kind", SkillKind.ACTIVE),
                            "status_effect": getattr(skill, "status_effect", ""),
                            "status_probability": getattr(skill, "status_probability", 0.0),
                            "status_duration": getattr(skill, "status_duration", 1),
                            "damage_formula": getattr(skill, "damage_formula", {}),
                            "targets": getattr(skill, "targets", 1),
                        }
                    )
            except DatabaseError:
                # 获取模板技能失败，返回空列表
                logger.warning(
                    "Failed to load template skills for AI guest",
                    extra={"guest_template": getattr(template, "key", None)},
                    exc_info=True,
                )

    return data


def serialize_guest_for_report(combatant: Combatant) -> Dict[str, Any]:
    return {
        "name": combatant.name,
        "attack": combatant.attack,
        "defense": combatant.defense,
        "hp": combatant.max_hp,
        "max_hp": combatant.max_hp,
        "initial_hp": combatant.initial_hp or combatant.max_hp,
        "remaining_hp": max(0, combatant.hp),
        "rarity": combatant.rarity,
        "priority": combatant.priority,
        "template_key": combatant.template_key,
        "guest_id": combatant.guest_id,
        "level": combatant.level,
    }


def normalize_troop_loadout(
    loadout: Dict[str, int] | None,
    *,
    default_if_empty: bool = True,
) -> Dict[str, int]:
    templates = load_troop_templates()
    if not templates:
        return {}
    if not loadout:
        return default_troop_loadout() if default_if_empty else {}
    normalized: Dict[str, int] = {}
    for key in templates.keys():
        value = int(loadout.get(key, 0) or 0)
        normalized[key] = max(0, value)
    if not any(normalized.values()):
        return default_troop_loadout() if default_if_empty else {}
    return normalized


def build_guest_combatants(
    guests: List[Guest],
    side: str,
    limit: int | None = None,
    stat_bonuses: Optional[Dict[str, float]] = None,
    override_skill_keys: Optional[List[str]] = None,
) -> List[Combatant]:
    """
    构建门客战斗单位列表。

    Args:
        guests: 门客列表
        side: 阵营 ("attacker" 或 "defender")
        limit: 最大门客数量
        stat_bonuses: 属性加成字典 {"attack": 0.3, ...}
        override_skill_keys: 临时技能列表（覆盖门客原有技能）

    Returns:
        战斗单位列表
    """
    team: List[Combatant] = []
    use_limit = limit if limit is not None else MAX_SQUAD
    for guest in guests[:use_limit]:
        stats = guest.stat_block()

        # 应用属性加成
        bonuses = stat_bonuses or {}
        attack_mult = 1.0 + bonuses.get("attack", 0)
        defense_mult = 1.0 + bonuses.get("defense", 0)
        hp_mult = 1.0 + bonuses.get("hp", 0)
        agility_mult = 1.0 + bonuses.get("agility", 0)

        attack = int(stats["attack"] * attack_mult)
        defense = int(stats["defense"] * defense_mult)

        # 战斗中的血量上限（来自 max_hp 并叠加战斗加成）
        max_hp = int(stats["hp"] * hp_mult)

        # 门客参战血量使用持久化的 current_hp；AI/未保存门客默认满血
        if getattr(guest, "pk", None) is not None:
            raw_current_hp = getattr(guest, "current_hp", 0) or 0
            # 应用 hp_mult 保证加成下血量比例不失真，但不超过 max_hp
            hp = min(max_hp, int(raw_current_hp * hp_mult))
            # 确保至少有1点HP（防止0 HP进入战斗）
            hp = max(1, hp)
        else:
            # AI/未保存门客默认满血
            hp = max_hp

        base_agility = getattr(guest, "agility", DEFAULT_GUEST_AGILITY)
        intellect_value = stats.get(
            "intellect", getattr(guest, "intellect", DEFAULT_GUEST_AGILITY)
        )
        troop_speed = max(MIN_SPEED_BONUS, intellect_value // INTELLECT_TO_SPEED_DIVISOR)
        agility = int((base_agility + troop_speed) * agility_mult)

        # priority 将由 assign_agility_based_priorities() 根据全场敏捷分布动态分配
        priority = 0
        team.append(
            Combatant(
                name=guest.display_name,
                guest_id=getattr(guest, "id", None),
                attack=attack,
                defense=defense,
                hp=hp,
                max_hp=max_hp,
                side=side,
                rarity=guest.rarity,
                luck=getattr(guest, "luck", DEFAULT_LUCK),
                agility=agility,
                priority=priority,
                kind="guest",
                troop_strength=0,
                initial_hp=hp,  # 记录战斗开始时的HP，用于计算本场损失
                template_key=guest.template.key,
                skills=serialize_skills(guest, override_skill_keys=override_skill_keys),
                force_attr=getattr(guest, "force", 100),
                intellect_attr=getattr(guest, "intellect", 100),
                defense_attr=getattr(guest, "defense_stat", stats["defense"]),
                level=getattr(guest, "level", 1),  # 传入门客等级
            )
        )
    return team


def build_named_ai_guests(
    guest_keys: List[str | Dict[str, Any]],
    level: int = 50
) -> List[Guest]:
    """
    构建指定模板的AI门客，使用随机属性成长。

    Args:
        guest_keys: 门客配置列表，支持两种格式：
            - 字符串: 门客模板key（向后兼容）
            - 字典: {"key": "template_key", "skills": ["skill1", "skill2"]}（新格式）
        level: 门客等级（默认50）

    Returns:
        AI门客列表，属性根据等级随机成长（包含自由属性点自动分配）
        如果配置了单独技能，门客对象会有 _override_skills 属性
    """
    from guests.models import RARITY_SKILL_POINT_GAINS
    from guests.utils.attribute_growth import allocate_level_up_attributes

    # 解析配置，提取 template_key 和单独技能配置
    parsed_configs: List[Dict[str, Any]] = []
    template_keys_to_fetch: List[str] = []

    for entry in guest_keys:
        if isinstance(entry, str):
            # 向后兼容：字符串格式
            parsed_configs.append({"key": entry, "skills": None})
            template_keys_to_fetch.append(entry)
        elif isinstance(entry, dict):
            # 新格式：字典格式
            key = entry.get("key", "")
            skills = entry.get("skills")  # 可以是 None 或技能列表
            parsed_configs.append({"key": key, "skills": skills})
            if key:
                template_keys_to_fetch.append(key)

    # 使用缓存获取模板（避免每次战斗都查询数据库）
    all_templates = _get_all_guest_templates()
    templates = {key: all_templates[key] for key in template_keys_to_fetch if key in all_templates}
    guests: List[Guest] = []

    for config in parsed_configs:
        template_key = config["key"]
        override_skills = config["skills"]

        template = templates.get(template_key)
        if not template:
            continue

        # 创建基础门客实例，从模板获取初始属性
        dummy_guest = Guest(
            template=template,
            level=level,
            attack_bonus=40,
            defense_bonus=40,
            # 设置基础属性（从模板获取）
            force=template.base_attack,
            intellect=template.base_intellect,
            defense_stat=template.base_defense,
            agility=template.base_agility,
            luck=template.base_luck,
            gender=template.default_gender,
            morality=template.default_morality,
        )

        # 如果等级大于1，计算并应用属性成长
        if level > 1:
            growth_levels = level - 1

            # 1. 随机属性成长
            growth = allocate_level_up_attributes(dummy_guest, levels=growth_levels)
            dummy_guest.force += growth.get("force", 0)
            dummy_guest.intellect += growth.get("intellect", 0)
            dummy_guest.defense_stat += growth.get("defense", 0)
            dummy_guest.agility += growth.get("agility", 0)

            # 2. 自由属性点自动分配（AI按职业权重分配）
            per_level_points = RARITY_SKILL_POINT_GAINS.get(template.rarity, 1)
            total_attribute_points = per_level_points * growth_levels

            if total_attribute_points > 0:
                attr_allocation = _allocate_ai_attribute_points(dummy_guest, total_attribute_points)
                dummy_guest.force += attr_allocation.get("force", 0)
                dummy_guest.intellect += attr_allocation.get("intellect", 0)
                dummy_guest.defense_stat += attr_allocation.get("defense", 0)
                dummy_guest.agility += attr_allocation.get("agility", 0)

        # 设置单独的技能覆盖（如果配置了）
        if override_skills is not None:
            dummy_guest._override_skills = override_skills

        guests.append(dummy_guest)

    return guests


def _allocate_ai_attribute_points(guest: Guest, total_points: int) -> Dict[str, int]:
    """
    为AI门客自动分配自由属性点（按职业权重）。

    Args:
        guest: 门客实例（用于判断职业）
        total_points: 总属性点数

    Returns:
        属性分配字典 {"force": X, "intellect": Y, "defense": Z, "agility": W}
    """
    from guests.utils.attribute_growth import MILITARY_ATTRIBUTE_WEIGHTS, CIVIL_ATTRIBUTE_WEIGHTS

    # 根据职业选择权重
    if guest.archetype == "military":
        weights = MILITARY_ATTRIBUTE_WEIGHTS
    else:  # civil
        weights = CIVIL_ATTRIBUTE_WEIGHTS

    # 创建加权选择池
    choices = []
    for attr, weight in weights.items():
        choices.extend([attr] * weight)

    # 使用随机分配（每次调用会产生不同结果）
    allocation = {"force": 0, "intellect": 0, "defense": 0, "agility": 0}
    for _ in range(total_points):
        attr = random.choice(choices)
        allocation[attr] += 1

    return allocation


def build_ai_guests(rng: random.Random) -> List[Guest]:
    # 使用缓存获取模板（避免每次战斗都查询数据库）
    all_templates = _get_all_guest_templates()
    templates = list(all_templates.values())
    rng.shuffle(templates)
    guests: List[Guest] = []
    for template in templates[:MAX_SQUAD]:
        dummy_guest = Guest(
            template=template,
            level=10,
            attack_bonus=20,
            defense_bonus=20,
        )
        guests.append(dummy_guest)
    return guests


def _build_tech_effects(
    troop_class: str,
    tech_levels: Dict[str, int],
) -> Dict[str, float]:
    """
    构建兵种的武艺技术特殊效果参数

    Args:
        manor: 庄园实例
        troop_class: 兵种类别 (dao/qiang/jian/quan/gong)
        tech_levels: 可选的科技等级字典（供敌方使用）

    Returns:
        特殊效果参数字典
    """
    from core.game_data.technology import get_tech_bonus_from_levels

    effects: Dict[str, float] = {}

    def _bonus(effect: str) -> float:
        return get_tech_bonus_from_levels(tech_levels, effect, troop_class)

    if troop_class == "dao":
        # 狂狼必杀：双倍打击几率
        double_strike = _bonus("double_strike_chance")
        if double_strike > 0:
            effects["double_strike_chance"] = double_strike

    elif troop_class == "qiang":
        # 反戈一击：反击几率（基础伤害30%固定）
        counter = _bonus("counter_attack_chance")
        if counter > 0:
            effects["counter_attack_chance"] = counter
            effects["counter_attack_damage"] = 0.30  # 固定30%伤害

    elif troop_class == "jian":
        # 护身剑罡：反弹伤害（基础10% + 每级10%）
        reflect = _bonus("damage_reflect")
        if reflect > 0:
            effects["damage_reflect"] = 0.10 + reflect  # 基础10% + 等级加成
        # 驭剑之术：先攻伤害（基础50% + 每级10%）
        preempt = _bonus("preemptive_strike")
        if preempt > 0:
            effects["preemptive_damage"] = 0.50 + preempt

    elif troop_class == "quan":
        # 万宗归流：远程防御
        ranged_def = _bonus("ranged_defense")
        if ranged_def > 0:
            effects["ranged_defense"] = ranged_def
        # 五气朝元：恢复几率（每级10%几率，恢复当前生命10%）
        heal = _bonus("battle_heal_chance")
        if heal > 0:
            effects["battle_heal_chance"] = heal
            effects["battle_heal_amount"] = 0.10  # 固定恢复10%当前生命

    elif troop_class == "gong":
        # 凤舞九天：额外先攻伤害（基础35% + 每级10%）
        extra_range = _bonus("extra_range")
        if extra_range > 0:
            effects["extra_range_damage"] = 0.35 + extra_range
        # 短刃杀法：近战攻击加成
        melee = _bonus("melee_attack")
        if melee > 0:
            effects["melee_attack_bonus"] = melee

    return effects


def build_troop_combatants(
    loadout: Dict[str, int],
    side: str,
    manor=None,
    tech_levels: Optional[Dict[str, int]] = None,
) -> List[Combatant]:
    """
    构建小兵战斗单位列表

    Args:
        loadout: 兵种配置 {troop_key: count}
        side: 阵营 ("attacker" 或 "defender")
        manor: 庄园实例（可选，用于应用武艺技术加成）
        tech_levels: 可选的科技等级字典（供敌方使用）

    Returns:
        小兵战斗单位列表
    """
    from core.game_data.technology import get_troop_class_for_key, get_troop_stat_bonuses_from_levels

    templates = load_troop_templates()
    troops: List[Combatant] = []

    effective_levels = tech_levels
    if effective_levels is None and manor is not None:
        # Avoid importing gameplay.services.technology here; we only need current levels.
        effective_levels = {t.tech_key: t.level for t in manor.technologies.all()}

    for key, count in loadout.items():
        if count <= 0:
            continue
        definition = templates.get(key)
        if not definition:
            continue

        # 获取兵种类别（无论是否有manor，都需要设置，用于克制判定等）
        troop_class = get_troop_class_for_key(key) or ""

        # 获取基础属性加成
        bonuses: Dict[str, float] = {}
        if effective_levels is not None:
            bonuses = get_troop_stat_bonuses_from_levels(effective_levels, key)

        attack_mult = 1.0 + bonuses.get("attack", 0)
        defense_mult = 1.0 + bonuses.get("defense", 0)
        hp_mult = 1.0 + bonuses.get("hp", 0)
        agility_mult = 1.0 + bonuses.get("agility", 0)

        # 应用加成到单位属性
        unit_attack = int(definition.get("base_attack", 30) * attack_mult)
        unit_defense = int(definition.get("base_defense", 20) * defense_mult)
        unit_hp = int(definition.get("base_hp", 80) * hp_mult)
        base_agility = definition.get("speed_bonus", 0)
        agility = int(base_agility * agility_mult) if base_agility > 0 else base_agility

        # 计算总属性
        attack = unit_attack * count
        defense = unit_defense * count
        hp = unit_hp * count

        # 获取特殊效果
        tech_effects: Dict[str, float] = {}
        if effective_levels is not None and troop_class:
            tech_effects = _build_tech_effects(troop_class, tech_levels=effective_levels)

        # 确定优先级
        priority = int(definition["priority"])

        # 驭剑之术：剑系提前一轮行动（priority -1）
        if troop_class == "jian" and tech_effects.get("preemptive_damage", 0) > 0:
            priority = -1

        # 凤舞九天：弓箭额外先攻一回合（priority -2）
        if troop_class == "gong" and tech_effects.get("extra_range_damage", 0) > 0:
            priority = -2

        troops.append(
            Combatant(
                name=definition["label"],
                attack=attack,
                defense=defense,
                hp=hp,
                max_hp=hp,
                side=side,
                rarity="troop",
                luck=30,
                agility=agility,
                priority=priority,
                kind="troop",
                troop_strength=count,
                initial_troop_strength=count,
                initial_hp=hp,  # 记录战斗开始时的HP
                unit_attack=unit_attack,
                unit_defense=unit_defense,
                unit_hp=unit_hp,
                template_key=key,
                skills=[],
                troop_class=troop_class,
                tech_effects=tech_effects,
            )
        )
    return troops


def generate_ai_loadout(rng: random.Random) -> Dict[str, int]:
    templates = load_troop_templates()
    loadout: Dict[str, int] = {}
    for key, definition in templates.items():
        base = definition.get("default_count", 120)
        jitter = rng.randint(-int(base * 0.2), int(base * 0.2)) if base else 0
        loadout[key] = max(0, int(base + jitter))
    return loadout


def assign_agility_based_priorities(
    attacker_units: List[Combatant],
    defender_units: List[Combatant],
) -> None:
    """
    根据全场敏捷分布动态分配优先级（精锐制）

    规则：
    - 全场最快的25%门客 → priority -1（先锋，第1回合参战）
    - 其余75%门客 → priority 0（主力，第2回合参战）

    优势：
    - 整体敏捷高的一方会占据更多先手位
    - 敏捷碾压时能第1回合单方面输出
    - 自然限制敏捷投资（只有前25%有价值）
    - 鼓励多样化配队（速攻型+输出型+坦克型）

    小兵保持原有 priority（弓箭手 -1，枪兵/骑兵 0）
    """
    # 收集双方所有门客
    all_units = attacker_units + defender_units
    guests = [u for u in all_units if u.kind == "guest"]

    if not guests:
        return

    # 按敏捷从高到低排序
    sorted_guests = sorted(guests, key=lambda g: g.agility, reverse=True)
    total = len(sorted_guests)

    # 前25%是先锋，后75%是主力
    cutoff = max(1, int(total * VANGUARD_RATIO))

    for idx, guest in enumerate(sorted_guests):
        if idx < cutoff:
            guest.priority = -1  # 先锋（前25%）
        else:
            guest.priority = 0  # 主力（后75%）
