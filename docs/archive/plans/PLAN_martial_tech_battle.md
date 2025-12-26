# 武艺技术战斗效果实现计划

## 一、技术效果详细说明

### 1.1 刀类技术

| 技术名称 | 效果类型 | 说明 |
|---------|---------|------|
| 力劈华山 | `troop_attack` | 每级刀系兵种武力+10% |
| 横炼铁杉 | `troop_defense` | 每级刀系兵种防御+10% |
| 疾风碎步 | `troop_agility` | 每级刀系兵种敏捷+10% |
| 蓄日回元 | `troop_hp` | 每级刀系兵种生命值+10% |
| 破甲一击 | `troop_vs_class` | 对剑系兵种每级额外伤害+10% |
| 狂狼必杀 | `double_strike_chance` | 每级双倍打击几率+10% |

### 1.2 枪类技术

| 技术名称 | 效果类型 | 说明 |
|---------|---------|------|
| 破日枪法 | `troop_attack` | 每级枪系兵种武力+10% |
| 金钟罡气 | `troop_defense` | 每级枪系兵种防御+10% |
| 乾坤挪移 | `troop_agility` | 每级枪系兵种敏捷+10% |
| 体血倍增 | `troop_hp` | 每级枪系兵种生命值+10% |
| 攻坚破城 | `siege_damage` | 对防御建筑每级额外伤害+10%（**暂不实现**） |
| 反戈一击 | `counter_attack_chance` | 被攻击时有几率反击，造成30%伤害，每级反击几率+10% |

### 1.3 剑类技术

| 技术名称 | 效果类型 | 说明 |
|---------|---------|------|
| 长虹贯日 | `troop_attack` | 每级剑系兵种武力+10% |
| 纯阳护体 | `troop_defense` | 每级剑系兵种防御+10% |
| 飘絮身法 | `troop_agility` | 每级剑系兵种敏捷+10% |
| 回春转气 | `troop_hp` | 每级剑系兵种生命值+10% |
| 护身剑罡 | `damage_reflect` | 被攻击时自动反弹10%伤害，每级反弹伤害+10% |
| 驭剑之术 | `preemptive_strike` | 提前一轮进攻，造成50%伤害，每级伤害+10% |

### 1.4 拳类技术

| 技术名称 | 效果类型 | 说明 |
|---------|---------|------|
| 通背神拳 | `troop_attack` | 每级拳系兵种武力+10% |
| 金钟罩体 | `troop_defense` | 每级拳系兵种防御+10% |
| 凌波渡虚 | `troop_agility` | 每级拳系兵种敏捷+10% |
| 炼气回元 | `troop_hp` | 每级拳系兵种生命值+10% |
| 万宗归流 | `ranged_defense` | 对远程攻击每级防御+10%（弓箭手先攻/先锋回合视为远程攻击） |
| 五气朝元 | `battle_heal_chance` | 每级有10%几率恢复当前生命值的10% |

### 1.5 弓箭类技术

| 技术名称 | 效果类型 | 说明 |
|---------|---------|------|
| 百步穿杨 | `troop_attack` | 每级弓箭系兵种武力+10% |
| 天地反转 | `troop_defense` | 每级弓箭系兵种防御+10% |
| 御风追月 | `troop_agility` | 每级弓箭系兵种敏捷+10% |
| 云流转气 | `troop_hp` | 每级弓箭系兵种生命值+10% |
| 凤舞九天 | `extra_range` | 额外先攻一回合（射程+1），最大射程攻击造成35%伤害，每级+10% |
| 短刃杀法 | `melee_attack` | 近战攻击力每级+10%（先攻/先锋回合之后视为近战） |

---

## 二、战斗阶段定义

### 2.1 回合类型

```
战斗流程：
┌─────────────────────────────────────────────────────────┐
│ 先锋回合 (priority = -2)                                │
│   - 弓箭手「凤舞九天」额外先攻回合                       │
│   - 攻击力 = 35% + level×10%                            │
│   - 视为【远程攻击】                                     │
├─────────────────────────────────────────────────────────┤
│ 先攻回合 (priority = -1)                                │
│   - 弓箭手正常先攻                                       │
│   - 剑系「驭剑之术」提前进攻，攻击力 = 50% + level×10%  │
│   - 弓箭手视为【远程攻击】，剑系视为【近战攻击】         │
├─────────────────────────────────────────────────────────┤
│ 正常回合 (priority = 0)                                 │
│   - 所有兵种正常战斗                                     │
│   - 全部视为【近战攻击】                                 │
└─────────────────────────────────────────────────────────┘
```

### 2.2 攻击类型判定

| 攻击者 | 回合类型 | 攻击类型 |
|-------|---------|---------|
| 弓箭手 | 先锋回合 (凤舞九天) | 远程攻击 |
| 弓箭手 | 先攻回合 | 远程攻击 |
| 弓箭手 | 正常回合 | 近战攻击 |
| 剑系 | 先攻回合 (驭剑之术) | 近战攻击 |
| 其他兵种 | 任意回合 | 近战攻击 |

---

## 三、现状分析

### 3.1 已有配置（technology_templates.yaml）

技术配置已完成，包含：
- 5类兵种 × 4项基础属性 = 20项
- 5类兵种 × 2项特殊效果 = 10项
- 共30项武艺技术

### 3.2 已有服务（gameplay/services/technology.py）

```python
get_tech_bonus(manor, effect_type, troop_class) -> float  # 获取技术加成倍率
get_troop_stat_bonuses(manor, troop_key) -> Dict[str, float]  # 获取兵种属性加成
get_troop_class_for_key(troop_key) -> str  # 获取兵种所属类别
```

### 3.3 当前问题

1. `build_troop_combatants()` 没有调用技术加成
2. 战斗循环没有实现特殊效果逻辑
3. 小兵没有 `manor` 上下文，无法获取玩家技术等级
4. 没有区分远程攻击和近战攻击

---

## 四、实现方案

### 4.1 扩展 Combatant 数据结构

**文件**：`battle/combatants.py`

```python
@dataclass(slots=True)
class Combatant:
    # ... 现有字段 ...

    # 新增：兵种类别（dao/qiang/jian/quan/gong）
    troop_class: str = ""

    # 新增：特殊效果参数
    tech_effects: Dict[str, float] = field(default_factory=dict)
    # {
    #     "double_strike_chance": 0.3,      # 狂狼必杀：30%双倍打击
    #     "vs_jian_bonus": 0.2,             # 破甲一击：对剑系+20%伤害
    #     "counter_attack_chance": 0.4,     # 反戈一击：40%反击几率
    #     "damage_reflect": 0.3,            # 护身剑罡：30%反弹
    #     "preemptive_damage": 0.7,         # 驭剑之术：70%先攻伤害
    #     "ranged_defense": 0.5,            # 万宗归流：远程防御+50%
    #     "battle_heal_chance": 0.3,        # 五气朝元：30%恢复几率
    #     "extra_range_damage": 0.55,       # 凤舞九天：55%远程伤害
    #     "melee_attack_bonus": 0.2,        # 短刃杀法：近战+20%
    # }
```

### 4.2 修改 build_troop_combatants

**文件**：`battle/combatants.py`

```python
def build_troop_combatants(
    loadout: Dict[str, int],
    side: str,
    manor=None,  # 新增：用于获取技术加成
) -> List[Combatant]:
    from gameplay.services.technology import (
        get_troop_stat_bonuses,
        get_tech_bonus,
        get_troop_class_for_key,
    )

    templates = load_troop_templates()
    troops: List[Combatant] = []

    for key, count in loadout.items():
        if count <= 0:
            continue
        definition = templates.get(key)
        if not definition:
            continue

        # 获取兵种类别
        troop_class = get_troop_class_for_key(key) if manor else ""

        # 获取基础属性加成
        bonuses = get_troop_stat_bonuses(manor, key) if manor else {}
        attack_mult = 1.0 + bonuses.get("attack", 0)
        defense_mult = 1.0 + bonuses.get("defense", 0)
        hp_mult = 1.0 + bonuses.get("hp", 0)
        agility_mult = 1.0 + bonuses.get("agility", 0)

        # 应用加成到基础属性
        unit_attack = int(definition.get("base_attack", 30) * attack_mult)
        unit_defense = int(definition.get("base_defense", 20) * defense_mult)
        unit_hp = int(definition.get("base_hp", 80) * hp_mult)
        agility = int(definition["speed_bonus"] * agility_mult)

        # 获取特殊效果
        tech_effects = {}
        if manor and troop_class:
            tech_effects = _build_tech_effects(manor, troop_class)

        # 处理驭剑之术：剑系提前一轮行动
        priority = int(definition["priority"])
        if troop_class == "jian" and tech_effects.get("preemptive_damage", 0) > 0:
            priority = -1

        # 处理凤舞九天：弓箭额外先攻一回合
        if troop_class == "gong" and tech_effects.get("extra_range_damage", 0) > 0:
            priority = -2  # 比普通先攻更早

        troops.append(
            Combatant(
                # ... 其他字段 ...
                troop_class=troop_class,
                tech_effects=tech_effects,
                priority=priority,
            )
        )

    return troops


def _build_tech_effects(manor, troop_class: str) -> Dict[str, float]:
    """构建兵种的特殊效果参数"""
    from gameplay.services.technology import get_tech_bonus

    effects = {}

    if troop_class == "dao":
        # 破甲一击：对剑系额外伤害
        vs_jian = get_tech_bonus(manor, "troop_vs_class", "dao")
        if vs_jian > 0:
            effects["vs_jian_bonus"] = vs_jian
        # 狂狼必杀：双倍打击几率
        double_strike = get_tech_bonus(manor, "double_strike_chance", "dao")
        if double_strike > 0:
            effects["double_strike_chance"] = double_strike

    elif troop_class == "qiang":
        # 反戈一击：反击几率（基础伤害30%固定）
        counter = get_tech_bonus(manor, "counter_attack_chance", "qiang")
        if counter > 0:
            effects["counter_attack_chance"] = counter
            effects["counter_attack_damage"] = 0.30  # 固定30%伤害

    elif troop_class == "jian":
        # 护身剑罡：反弹伤害（基础10% + 每级10%）
        reflect = get_tech_bonus(manor, "damage_reflect", "jian")
        if reflect > 0:
            effects["damage_reflect"] = 0.10 + reflect  # 基础10% + 等级加成
        # 驭剑之术：先攻伤害（基础50% + 每级10%）
        preempt = get_tech_bonus(manor, "preemptive_strike", "jian")
        if preempt > 0:
            effects["preemptive_damage"] = 0.50 + preempt

    elif troop_class == "quan":
        # 万宗归流：远程防御
        ranged_def = get_tech_bonus(manor, "ranged_defense", "quan")
        if ranged_def > 0:
            effects["ranged_defense"] = ranged_def
        # 五气朝元：恢复几率（每级10%几率，恢复当前生命10%）
        heal = get_tech_bonus(manor, "battle_heal_chance", "quan")
        if heal > 0:
            effects["battle_heal_chance"] = heal
            effects["battle_heal_amount"] = 0.10  # 固定恢复10%当前生命

    elif troop_class == "gong":
        # 凤舞九天：额外先攻伤害（基础35% + 每级10%）
        extra_range = get_tech_bonus(manor, "extra_range", "gong")
        if extra_range > 0:
            effects["extra_range_damage"] = 0.35 + extra_range
        # 短刃杀法：近战攻击加成
        melee = get_tech_bonus(manor, "melee_attack", "gong")
        if melee > 0:
            effects["melee_attack_bonus"] = melee

    return effects
```

### 4.3 战斗循环中实现特殊效果

**文件**：`battle/simulation_core.py`

#### 4.3.1 判断攻击类型

```python
def is_ranged_attack(actor: Combatant, round_priority: int) -> bool:
    """判断是否为远程攻击"""
    if actor.troop_class != "gong":
        return False
    # 弓箭手在先锋回合(-2)和先攻回合(-1)视为远程攻击
    return round_priority < 0
```

#### 4.3.2 在 perform_attack 中实现效果

```python
def perform_attack(actor, attacker_team, defender_team, rng, round_priority=0):
    # ... 选择目标 ...

    # 1. 计算基础伤害
    attack_value = effective_attack_value(actor, target)
    defense_value = effective_defense_value(target, actor)

    # 2. 应用远程防御（万宗归流）
    if is_ranged_attack(actor, round_priority):
        ranged_def = target.tech_effects.get("ranged_defense", 0)
        if ranged_def > 0:
            defense_value = int(defense_value * (1 + ranged_def))

    # 3. 应用近战攻击加成（短刃杀法）
    if actor.troop_class == "gong" and not is_ranged_attack(actor, round_priority):
        melee_bonus = actor.tech_effects.get("melee_attack_bonus", 0)
        if melee_bonus > 0:
            attack_value = int(attack_value * (1 + melee_bonus))

    # 4. 应用克制加成（破甲一击：刀→剑）
    if actor.troop_class == "dao" and target.troop_class == "jian":
        vs_bonus = actor.tech_effects.get("vs_jian_bonus", 0)
        if vs_bonus > 0:
            attack_value = int(attack_value * (1 + vs_bonus))

    # 5. 应用先攻伤害减免（驭剑之术）
    if actor.troop_class == "jian" and round_priority == -1:
        preempt_mult = actor.tech_effects.get("preemptive_damage", 0)
        if preempt_mult > 0:
            # 用先攻伤害倍率替代80%减免
            damage = int(base_damage * preempt_mult)

    # 6. 应用凤舞九天伤害（先锋回合）
    if actor.troop_class == "gong" and round_priority == -2:
        extra_range_mult = actor.tech_effects.get("extra_range_damage", 0)
        if extra_range_mult > 0:
            damage = int(base_damage * extra_range_mult)

    # 7. 双倍打击（狂狼必杀）
    double_strike = actor.tech_effects.get("double_strike_chance", 0)
    is_double_strike = False
    if double_strike > 0 and rng.random() < double_strike:
        damage *= 2
        is_double_strike = True

    # 8. 造成伤害
    target.hp -= damage

    # 9. 伤害反弹（护身剑罡）
    reflect_ratio = target.tech_effects.get("damage_reflect", 0)
    reflect_damage = 0
    if reflect_ratio > 0 and target.troop_class == "jian":
        reflect_damage = int(damage * reflect_ratio)
        actor.hp -= reflect_damage

    # 10. 反击（反戈一击）
    counter_chance = target.tech_effects.get("counter_attack_chance", 0)
    counter_damage = 0
    if counter_chance > 0 and target.hp > 0 and rng.random() < counter_chance:
        counter_mult = target.tech_effects.get("counter_attack_damage", 0.30)
        counter_damage = int(effective_attack_value(target, actor) * counter_mult)
        actor.hp -= counter_damage

    # 记录战报
    entry = {
        # ... 现有字段 ...
        "is_double_strike": is_double_strike,
        "reflect_damage": reflect_damage,
        "counter_damage": counter_damage,
        "attack_type": "ranged" if is_ranged_attack(actor, round_priority) else "melee",
    }
```

#### 4.3.3 回合开始时的恢复（五气朝元）

```python
def apply_battle_heal(units: List[Combatant], rng: random.Random) -> List[Dict]:
    """回合开始时应用战斗恢复效果"""
    heals = []
    for unit in units:
        if unit.hp <= 0:
            continue
        heal_chance = unit.tech_effects.get("battle_heal_chance", 0)
        if heal_chance <= 0:
            continue
        if rng.random() < heal_chance:
            heal_amount = unit.tech_effects.get("battle_heal_amount", 0.10)
            healed = int(unit.hp * heal_amount)
            unit.hp = min(unit.max_hp, unit.hp + healed)
            heals.append({
                "unit": unit.name,
                "healed": healed,
                "new_hp": unit.hp,
            })
    return heals
```

### 4.4 修改回合处理支持先锋回合

**文件**：`battle/simulation_core.py`

```python
def resolve_priority_phases(attacker_team, defender_team, rng):
    """处理先锋回合(-2)和先攻回合(-1)"""
    participants = alive(attacker_team) + alive(defender_team)
    priority_values = sorted({c.priority for c in participants if c.priority < 0})

    # priority_values 可能是 [-2, -1] 或 [-1]
    # -2: 凤舞九天先锋回合
    # -1: 弓箭手先攻 + 驭剑之术先攻

    rounds = []
    next_round_no = 1

    for priority in priority_values:
        # ... 处理该优先级的回合 ...
        # 传递 round_priority 到 perform_attack
```

---

## 五、实现步骤

### 阶段一：基础属性加成（必须）

1. [ ] 修改 `Combatant` 添加 `troop_class` 和 `tech_effects` 字段
2. [ ] 修改 `build_troop_combatants()` 签名，添加 `manor` 参数
3. [ ] 实现 `_build_tech_effects()` 辅助函数
4. [ ] 应用 attack/defense/hp/agility 基础加成
5. [ ] 更新所有调用点传入 `manor` 参数
6. [ ] 测试：验证技术等级影响小兵属性

### 阶段二：简单特殊效果

| 序号 | 效果 | 技术名 | 实现难度 |
|-----|------|-------|---------|
| 1 | 双倍打击 | 狂狼必杀 | 低 |
| 2 | 克制加成 | 破甲一击 | 低 |
| 3 | 伤害反弹 | 护身剑罡 | 低 |
| 4 | 反击 | 反戈一击 | 中 |

### 阶段三：战斗恢复

| 序号 | 效果 | 技术名 | 实现难度 |
|-----|------|-------|---------|
| 5 | 战斗恢复 | 五气朝元 | 中 |

### 阶段四：攻击类型与先攻系统

| 序号 | 效果 | 技术名 | 实现难度 |
|-----|------|-------|---------|
| 6 | 远程防御 | 万宗归流 | 中 |
| 7 | 近战攻击 | 短刃杀法 | 中 |
| 8 | 先攻伤害 | 驭剑之术 | 高 |
| 9 | 额外先攻 | 凤舞九天 | 高 |

### 阶段五：战报展示

1. [ ] 在战报事件中记录特殊效果触发
2. [ ] 前端模板展示：双倍打击、反击、恢复、反弹等

### 暂不实现

- 攻坚破城（无防御建筑系统）

---

## 六、涉及文件

| 文件 | 修改内容 |
|-----|---------|
| `battle/combatants.py` | Combatant 添加字段，build_troop_combatants 应用加成 |
| `battle/simulation_core.py` | perform_attack 实现特殊效果，支持先锋回合 |
| `battle/status_manager.py` | 回合开始的战斗恢复 |
| `battle/services.py` | 调用点传入 manor |
| `battle/tasks.py` | 调用点传入 manor |
| `gameplay/services/technology.py` | 可能需要调整加成计算 |
| `battle/templates/battle/report_detail.html` | 展示特殊效果 |

---

## 七、数值平衡

### 7.1 满级效果（10级）

| 效果 | 数值 |
|-----|------|
| 基础属性加成 | +100%（攻/防/血/敏翻倍） |
| 双倍打击几率 | 100%（必定双倍） |
| 反击几率 | 100%（必定反击） |
| 伤害反弹 | 110%（10%基础 + 100%加成） |
| 先攻伤害 | 150%（50%基础 + 100%加成） |
| 远程防御 | +100% |
| 战斗恢复几率 | 100%（必定恢复） |
| 凤舞九天伤害 | 135%（35%基础 + 100%加成） |
| 近战攻击 | +100% |
| 克制伤害 | +100% |

### 7.2 平衡性考虑

- 满级技术加成非常强（+100%），需要实战测试
- AI 对手不应用技术加成，玩家有明显优势
- 可考虑：
  - 降低 `effect_per_level` 从 0.10 到 0.05
  - 或增加升级难度/成本

---

## 八、测试计划

1. **单元测试**：
   - 测试 `_build_tech_effects()` 返回正确参数
   - 测试各效果触发逻辑

2. **集成测试**：
   - 技术等级 0 vs 10 的战斗结果对比
   - 特殊效果触发率验证
   - 远程/近战攻击类型正确判定

3. **手动测试**：
   - 升级武艺技术后观察战斗变化
   - 战报中查看效果触发记录
   - 刀系打剑系验证克制加成
