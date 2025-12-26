# 战斗调试脚本设计方案

> 版本：v1.0
> 设计日期：2025-12-11

---

## 目录

- [一、设计目标](#一设计目标)
- [二、架构设计](#二架构设计)
- [三、功能模块](#三功能模块)
- [四、使用示例](#四使用示例)
- [五、配置文件](#五配置文件)
- [六、核心实现](#六核心实现)
- [七、输出格式](#七输出格式)
- [八、实施计划](#八实施计划)

---

## 一、设计目标

### 1.1 核心需求

✅ **快速配置战斗**
- 简单语法配置攻守双方（门客+小兵）
- 支持预设配置快速加载
- 可临时覆盖参数

✅ **参数化模拟**
- 动态调整倍率参数（屠戮、攻防缩放、减伤等）
- 不修改源代码
- 支持参数隔离和恢复

✅ **战斗分析**
- 详细战斗过程展示（逐回合）
- 统计关键指标（回合数、击杀数、存活率）
- 技能触发统计

✅ **批量调参**
- 网格搜索/区间扫描
- 对比多个配置
- 导出结果（CSV/JSON）

✅ **可视化输出**
- 终端友好的表格显示
- 支持详细/简要模式
- 支持数据导出

---

## 二、架构设计

### 2.1 目录结构

```
web_game_v5/
├── battle_debugger/
│   ├── __init__.py
│   ├── cli.py              # 命令行入口（Django Command）
│   ├── config.py           # 配置加载与管理
│   ├── simulator.py        # 战斗模拟器（参数覆盖）
│   ├── analyzer.py         # 结果分析器
│   ├── tuner.py            # 参数调优器
│   ├── reporter.py         # 报告生成器
│   └── presets/            # 预设配置目录
│       ├── guest_only.yaml
│       ├── troop_heavy.yaml
│       ├── balanced.yaml
│       └── boss_fight.yaml
└── docs/
    └── battle_debugger_design.md  # 本文档
```

### 2.2 技术栈

```python
# 核心依赖
- Django Management Commands（CLI框架）
- PyYAML（配置文件）
- tabulate / rich（表格输出）
- contextlib（参数覆盖）
- 现有战斗系统（battle/）

# 可选依赖
- pandas（数据分析）
- matplotlib（图表生成）
```

---

## 三、功能模块

### 3.1 CLI模块 (`cli.py`)

**Django Management Command**：`python manage.py battle_debug`

#### **子命令**

```bash
# 1. 单次模拟
battle_debug simulate [OPTIONS]

# 2. 参数调优（网格搜索）
battle_debug tune [OPTIONS]

# 3. 配置对比
battle_debug compare [OPTIONS]

# 4. 批量测试
battle_debug batch [OPTIONS]

# 5. 列出预设
battle_debug presets
```

#### **通用选项**

```bash
--seed SEED                    # 随机种子（可复现）
--repeat N                     # 重复N次取平均值
--output {text,csv,json}       # 输出格式
--verbose                      # 详细模式（显示战斗过程）
--max-events N                 # 最多显示N个战斗事件
```

---

### 3.2 配置模块 (`config.py`)

#### **功能**

1. **加载YAML配置**
2. **解析命令行参数**
3. **合并预设与覆盖**
4. **校验配置完整性**

#### **配置对象**

```python
@dataclass
class BattleConfig:
    name: str
    attacker: PartyConfig
    defender: PartyConfig
    tunable_params: Dict[str, Any]
    seed: Optional[int] = None
    repeat: int = 1

@dataclass
class PartyConfig:
    guests: List[GuestConfig]
    troops: Dict[str, int]
    technology_level: int = 0
    technology_levels: Dict[str, int] = field(default_factory=dict)

@dataclass
class GuestConfig:
    template: str
    level: int
    force: Optional[int] = None
    intellect: Optional[int] = None
    defense: Optional[int] = None
    agility: Optional[int] = None
    luck: Optional[int] = None
    skills: List[str] = field(default_factory=list)
```

#### **核心方法**

```python
class ConfigLoader:
    def load_preset(self, preset_name: str) -> BattleConfig:
        """加载预设配置"""

    def load_yaml(self, file_path: str) -> BattleConfig:
        """从YAML文件加载"""

    def parse_cli_args(self, args) -> Dict[str, Any]:
        """解析命令行参数"""

    def merge_config(self, base: BattleConfig, overrides: dict) -> BattleConfig:
        """合并配置和覆盖"""

    def validate(self, config: BattleConfig) -> List[str]:
        """校验配置，返回错误列表"""
```

---

### 3.3 模拟器模块 (`simulator.py`)

#### **功能**

1. **构造战斗单位**（门客+小兵）
2. **参数覆盖**（Monkey Patch）
3. **执行战斗模拟**
4. **返回战斗报告**

#### **核心类**

```python
class BattleSimulator:
    def __init__(self, config: BattleConfig):
        self.config = config

    def build_party(self, party_cfg: PartyConfig, side: str) -> Tuple[List, List]:
        """构造门客和小兵战斗单位"""
        # 使用 battle.combatants.build_named_ai_guests
        # 使用 battle.combatants.build_guest_combatants
        # 使用 battle.combatants.build_troop_combatants

    def run_battle(self, params: Dict[str, Any], seed: int) -> dict:
        """在参数覆盖上下文中运行战斗"""
        with self._patch_params(params):
            return self._simulate(seed)

    def _patch_params(self, params: Dict[str, Any]):
        """参数覆盖上下文管理器"""
        # 返回 contextmanager

    def _simulate(self, seed: int) -> dict:
        """调用战斗系统，返回报告"""
        # 调用 battle.simulation_core.simulate_battle
```

#### **参数覆盖机制**

```python
@contextmanager
def patch_battle_params(params: Dict[str, Any]):
    """
    临时覆盖战斗参数，不修改源代码

    支持的参数：
    - slaughter_multiplier: 屠戮倍率
    - troop_attack_divisor_vs_guest: 小兵打门客的倍率除数
    - troop_attack_divisor_vs_troop: 小兵打小兵的倍率除数
    - troop_defense_divisor: 小兵防御缩放除数
    - guest_vs_troop_reduction_coeff: 门客打小兵减伤系数
    - counter_multiplier: 五行相克倍率
    - crit_chance: 暴击率
    - priority_target_weight: 优先目标权重
    """
    import battle.combat_math as cm
    import battle.simulation_core as sc

    # 保存原始函数
    originals = {}

    # 覆盖函数
    if "slaughter_multiplier" in params:
        originals["slaughter"] = cm.calculate_slaughter_multiplier
        base_mult = params["slaughter_multiplier"]
        def custom_slaughter(attacker, target):
            if getattr(attacker, "kind", "") != "guest":
                return 1.0
            if getattr(target, "kind", "") != "troop":
                return 1.0
            return base_mult
        cm.calculate_slaughter_multiplier = custom_slaughter

    if "troop_attack_divisor_vs_guest" in params or "troop_attack_divisor_vs_troop" in params:
        originals["attack"] = cm.effective_attack_value
        div_guest = params.get("troop_attack_divisor_vs_guest", 4.0)
        div_troop = params.get("troop_attack_divisor_vs_troop", 1.0)

        def custom_attack(actor, target=None):
            if getattr(actor, "kind", "") != "troop":
                return int(getattr(actor, "attack", 0))
            strength = cm._current_strength(actor)
            unit_attack = cm._unit_attack_value(actor)
            if target is not None and getattr(target, "kind", "") != "troop":
                multiplier = max(1.0, strength / div_guest)
            else:
                multiplier = max(1.0, strength / div_troop)
            return max(1, int(unit_attack * multiplier))
        cm.effective_attack_value = custom_attack

    # ... 其他参数覆盖

    try:
        yield
    finally:
        # 恢复原始函数
        for key, func in originals.items():
            if key == "slaughter":
                cm.calculate_slaughter_multiplier = func
            elif key == "attack":
                cm.effective_attack_value = func
            # ... 恢复其他
```

---

### 3.4 分析器模块 (`analyzer.py`)

#### **功能**

1. **提取战斗指标**
2. **统计技能触发**
3. **汇总回合数据**
4. **计算对比差异**

#### **核心类**

```python
class BattleAnalyzer:
    def extract_metrics(self, report: dict) -> BattleMetrics:
        """提取关键指标"""

    def summarize_rounds(self, report: dict, top_n: int = None) -> List[RoundSummary]:
        """汇总每回合数据"""

    def count_skill_triggers(self, report: dict) -> Dict[str, int]:
        """统计技能触发次数"""

    def compare_metrics(self, metrics_list: List[BattleMetrics]) -> ComparisonReport:
        """对比多个指标"""

@dataclass
class BattleMetrics:
    winner: str
    rounds: int
    attacker_troops_lost: int
    defender_troops_lost: int
    attacker_hp_loss_percent: float
    defender_hp_loss_percent: float
    skill_triggers: Dict[str, int]
    total_damage_dealt: int
    total_kills: int
    avg_damage_per_round: float

@dataclass
class RoundSummary:
    round_no: int
    priority_phase: Optional[int]
    events_count: int
    total_damage: int
    total_kills: int
    key_events: List[str]  # 重要事件描述
```

---

### 3.5 调优器模块 (`tuner.py`)

#### **功能**

1. **生成参数组合**（网格/区间）
2. **批量运行模拟**
3. **收集结果**
4. **筛选最优解**

#### **核心类**

```python
class BattleTuner:
    def __init__(self, config: BattleConfig, simulator: BattleSimulator):
        self.config = config
        self.simulator = simulator

    def grid_search(
        self,
        param_grid: Dict[str, List[Any]],
        repeat: int = 10,
        objective: str = "min_rounds"
    ) -> TuningResult:
        """网格搜索"""

    def range_scan(
        self,
        param: str,
        start: float,
        end: float,
        step: float,
        repeat: int = 10
    ) -> TuningResult:
        """区间扫描"""

    def compare_configs(
        self,
        configs: List[BattleConfig],
        repeat: int = 10
    ) -> ComparisonResult:
        """对比多个配置"""

@dataclass
class TuningResult:
    param_combinations: List[Dict[str, Any]]
    metrics_list: List[BattleMetrics]
    best_params: Dict[str, Any]
    best_metrics: BattleMetrics
```

---

### 3.6 报告器模块 (`reporter.py`)

#### **功能**

1. **格式化输出**（表格/CSV/JSON）
2. **渲染战斗过程**
3. **生成对比图表**

#### **核心类**

```python
class BattleReporter:
    def print_summary(self, metrics: BattleMetrics, verbose: bool = False):
        """打印摘要"""

    def print_rounds(self, report: dict, max_events: int = None):
        """打印回合详情"""

    def export_csv(self, metrics_list: List[BattleMetrics], file_path: str):
        """导出CSV"""

    def export_json(self, report: dict, file_path: str):
        """导出JSON"""

    def print_comparison_table(self, comparison: ComparisonResult):
        """打印对比表格"""
```

---

## 四、使用示例

### 4.1 快速模拟

```bash
# 使用预设配置
python manage.py battle_debug simulate --preset balanced

# 输出示例
┌─────────────────────────────────────────────────┐
│ 战斗模拟结果                                    │
├─────────────────────────────────────────────────┤
│ 配置: balanced (平衡配置测试)                  │
│ 种子: 123456                                    │
├─────────────────────────────────────────────────┤
│ 胜者: attacker                                  │
│ 回合: 3                                         │
│ 攻方兵损: 120 / 500 (24%)                      │
│ 守方兵损: 2000 / 2000 (100%)                   │
│ 攻方HP损失: 18%                                 │
└─────────────────────────────────────────────────┘

技能触发统计:
  dragon_roar: 2次
  stratagem_burst: 1次
```

### 4.2 自定义配置

```bash
python manage.py battle_debug simulate \
  --attacker-guest "dugu_qiubai:100:force=500,intellect=300" \
  --attacker-troops "dao_sheng:200,gong_sheng:300" \
  --defender-troops "qiang_sheng:2000" \
  --seed 999 \
  --verbose
```

### 4.3 参数调优

```bash
# 调整屠戮倍率
python manage.py battle_debug tune \
  --param slaughter_multiplier \
  --values 20,22,24,26,28,30 \
  --preset balanced \
  --repeat 10 \
  --output csv \
  --file tuning_results.csv

# 输出示例
参数调优结果:
┌──────────────┬────────┬──────────┬────────────┬────────────┐
│ 屠戮倍率     │ 胜率   │ 平均回合 │ 攻方损失   │ 守方损失   │
├──────────────┼────────┼──────────┼────────────┼────────────┤
│ 20           │ 100%   │ 3.8      │ 28%        │ 100%       │
│ 22           │ 100%   │ 3.2      │ 25%        │ 100%       │
│ 24           │ 100%   │ 2.9      │ 23%        │ 100%       │
│ 26           │ 100%   │ 2.6      │ 21%        │ 100%       │
│ 28           │ 100%   │ 2.4      │ 20%        │ 100%       │
│ 30 (当前)    │ 100%   │ 2.1      │ 18%        │ 100%       │
└──────────────┴────────┴──────────┴────────────┴────────────┘

最优参数: slaughter_multiplier=22 (平衡回合数与攻方损失)
```

### 4.4 网格搜索

```bash
python manage.py battle_debug tune \
  --grid "slaughter_multiplier:20,24,28" \
  --grid "troop_attack_divisor_vs_guest:4,5,6" \
  --preset balanced \
  --repeat 5 \
  --objective min_attacker_loss

# 输出：18个参数组合的对比结果
```

### 4.5 配置对比

```bash
python manage.py battle_debug compare \
  --configs config1.yaml,config2.yaml,config3.yaml \
  --repeat 10 \
  --seed 12345

# 输出示例
配置对比:
┌─────────────┬────────┬──────────┬────────────┐
│ 配置名      │ 胜率   │ 平均回合 │ 平均损失   │
├─────────────┼────────┼──────────┼────────────┤
│ config1     │ 95%    │ 3.2      │ 22%        │
│ config2     │ 100%   │ 2.8      │ 18%        │
│ config3     │ 88%    │ 4.1      │ 31%        │
└─────────────┴────────┴──────────┴────────────┘
```

### 4.6 详细战斗过程

```bash
python manage.py battle_debug simulate \
  --preset balanced \
  --verbose \
  --max-events 20

# 输出示例
═══════════════════════════════════════════════════
战斗开始 (seed: 123456)
═══════════════════════════════════════════════════

━━━ 回合 1 (先锋阶段, 优先级-2) ━━━
[#1] 弓箭神 → 枪圣 | 伤害:1850 | 击杀:138 | 暴击 | [远程]
[#2] 弓箭神 → 枪圣 | 伤害:1720 | 击杀:128 | [远程]

━━━ 回合 1 (先攻阶段, 优先级-1) ━━━
[#3] 独孤求败 → 枪圣 | 伤害:850 | 击杀:1043 | 技能:[龙吟破阵] | ×3目标
[#4] 无名老僧 → 枪圣 | 伤害:720 | 击杀:884 | 技能:[奇策突袭] | 眩晕
     └─ 枪圣 被眩晕 (1回合)

━━━ 回合 1 (正常) ━━━
[#5] 刀圣 → 枪圣 | 伤害:650 | 击杀:72 | [克制]
[#6] 枪圣 → 刀圣 | 伤害:1200 | 击杀:35 | [反击触发]
...

━━━ 回合 2 (正常) ━━━
[#7] 独孤求败 → 剑圣 | 伤害:920 | 击杀:328 | [克制]
     └─ 反弹:184伤害 → 独孤求败
...

═══════════════════════════════════════════════════
战斗结束
═══════════════════════════════════════════════════
胜者: attacker
总回合: 3
总伤害: 18,540
总击杀: 2,000
```

---

## 五、配置文件

### 5.1 预设配置示例

```yaml
# battle_debugger/presets/balanced.yaml

name: "平衡配置测试"
description: "3个门客 + 500小兵 vs 2000小兵"

attacker:
  guests:
    - template: dugu_qiubai
      level: 100
      force: 500
      intellect: 300
      defense: 300
      agility: 200
      luck: 100
      skills:
        - dragon_roar
        - stratagem_burst

    - template: wu_mu
      level: 80
      force: 400
      intellect: 250
      defense: 250
      skills:
        - stratagem_burst

    - template: nameless_monk
      level: 90
      archetype: civil
      force: 300
      intellect: 450
      defense: 280

  troops:
    dao_sheng: 200
    gong_sheng: 300

  technology_level: 8  # 统一科技等级

  # 或精细控制每个科技
  technology_levels:
    dao_attack: 10
    gong_speed: 9
    jian_defense: 8

defender:
  troops:
    qiang_sheng: 2000

  technology_level: 10

# 可调参数（可被命令行覆盖）
tunable_params:
  slaughter_multiplier: 30
  troop_attack_divisor_vs_guest: 4.0
  troop_attack_divisor_vs_troop: 1.0
  troop_defense_divisor: 2.0
  guest_vs_troop_reduction_coeff: 0.005
  counter_multiplier: 1.5
  crit_chance: 0.05
```

### 5.2 命令行覆盖

```bash
# 覆盖单个参数
python manage.py battle_debug simulate \
  --preset balanced \
  --override slaughter_multiplier=22 \
  --override troop_attack_divisor_vs_guest=5.0

# 覆盖门客属性
python manage.py battle_debug simulate \
  --preset balanced \
  --override attacker.guests.0.force=600 \
  --override attacker.guests.0.level=100
```

---

## 六、核心实现

### 6.1 参数覆盖详解

#### **支持的可调参数**

| 参数名 | 默认值 | 影响范围 | 代码位置 |
|-------|--------|----------|----------|
| slaughter_multiplier | 30 | 门客击杀小兵倍率 | combat_math.py:79 |
| troop_attack_divisor_vs_guest | 4.0 | 小兵打门客攻击除数 | combat_math.py:102 |
| troop_attack_divisor_vs_troop | 1.0 | 小兵打小兵攻击除数 | combat_math.py:106 |
| troop_defense_divisor | 2.0 | 小兵防御缩放除数 | combat_math.py:130 |
| guest_vs_troop_reduction_coeff | 0.005 | 门客打小兵减伤系数 | simulation_core.py:274 |
| guest_vs_troop_reduction_cap | 0.75 | 门客打小兵减伤上限 | simulation_core.py:274 |
| other_reduction_base | 120 | 其他减伤公式基数 | simulation_core.py:277 |
| other_reduction_coeff | 0.85 | 其他减伤公式系数 | simulation_core.py:277 |
| counter_multiplier | 1.5 | 五行相克倍率 | simulation_core.py:252 |
| crit_chance | 0.05 | 暴击率 | simulation_core.py:38 |
| crit_multiplier | 1.5 | 暴击倍率 | simulation_core.py:294 |
| preemptive_penalty | 0.8 | 先锋门客伤害惩罚 | simulation_core.py:305 |
| priority_target_weight | 0.6 | 优先目标选择权重 | simulation_core.py:21 |
| max_rounds | 16 | 最大回合数 | constants.py:6 |

#### **实现示例**

```python
# battle_debugger/simulator.py

from contextlib import contextmanager
from typing import Dict, Any
import battle.combat_math as cm
import battle.simulation_core as sc

@contextmanager
def patch_battle_params(params: Dict[str, Any]):
    """临时覆盖战斗参数"""

    # 保存原始值
    originals = {}

    # === 屠戮倍率 ===
    if "slaughter_multiplier" in params:
        originals["calc_slaughter"] = cm.calculate_slaughter_multiplier
        multiplier = params["slaughter_multiplier"]

        def custom_slaughter(attacker, target):
            if getattr(attacker, "kind", "") != "guest":
                return 1.0
            if getattr(target, "kind", "") != "troop":
                return 1.0
            return multiplier

        cm.calculate_slaughter_multiplier = custom_slaughter

    # === 攻击倍率 ===
    if "troop_attack_divisor_vs_guest" in params or "troop_attack_divisor_vs_troop" in params:
        originals["eff_attack"] = cm.effective_attack_value
        div_guest = params.get("troop_attack_divisor_vs_guest", 4.0)
        div_troop = params.get("troop_attack_divisor_vs_troop", 1.0)
        orig_eff_attack = cm.effective_attack_value

        def custom_attack(actor, target=None):
            if getattr(actor, "kind", "") != "troop":
                return orig_eff_attack(actor, target)

            strength = cm._current_strength(actor)
            unit_attack = cm._unit_attack_value(actor)

            if target is not None and getattr(target, "kind", "") != "troop":
                multiplier = max(1.0, strength / div_guest)
            else:
                multiplier = max(1.0, strength / div_troop)

            return max(1, int(unit_attack * multiplier))

        cm.effective_attack_value = custom_attack

    # === 防御倍率 ===
    if "troop_defense_divisor" in params:
        originals["eff_defense"] = cm.effective_defense_value
        divisor = params["troop_defense_divisor"]
        orig_eff_defense = cm.effective_defense_value

        def custom_defense(target, attacker=None):
            import math
            if getattr(target, "kind", "") != "troop":
                return orig_eff_defense(target, attacker)

            unit_defense = cm._unit_defense_value(target)
            strength = cm._current_strength(target)
            multiplier = max(1.0, math.sqrt(strength) / divisor)
            return max(1, int(unit_defense * multiplier))

        cm.effective_defense_value = custom_defense

    # === 减伤公式 ===
    # 需要在 perform_attack 中覆盖，比较复杂，可能需要包装整个函数

    # === 暴击率 ===
    if "crit_chance" in params:
        originals["calc_crit"] = sc.calculate_crit_chance
        chance = params["crit_chance"]

        def custom_crit(actor):
            return chance

        sc.calculate_crit_chance = custom_crit

    # === 相克倍率 ===
    # 需要在 perform_attack 中覆盖

    try:
        yield
    finally:
        # 恢复所有原始值
        for key, func in originals.items():
            if key == "calc_slaughter":
                cm.calculate_slaughter_multiplier = func
            elif key == "eff_attack":
                cm.effective_attack_value = func
            elif key == "eff_defense":
                cm.effective_defense_value = func
            elif key == "calc_crit":
                sc.calculate_crit_chance = func
```

---

### 6.2 构造战斗单位

```python
# battle_debugger/simulator.py

from battle.combatants import (
    build_named_ai_guests,
    build_guest_combatants,
    build_troop_combatants
)
from battle.troops import load_troop_templates
from guests.models import Guest, GuestTemplate, Skill

class BattleSimulator:
    def build_party(self, party_cfg: PartyConfig, side: str) -> Tuple[List, List]:
        """构造战斗单位"""

        guest_combatants = []
        troop_combatants = []

        # 构造门客
        if party_cfg.guests:
            for guest_cfg in party_cfg.guests:
                # 方案1：使用AI门客（无需数据库）
                ai_guests = build_named_ai_guests(
                    template_keys=[guest_cfg.template],
                    level=guest_cfg.level,
                    bonus_multiplier=0.0,  # 不使用加成倍率
                    skills=guest_cfg.skills or None,
                    side=side
                )

                # 手动设置属性覆盖
                if ai_guests:
                    guest = ai_guests[0]
                    if guest_cfg.force is not None:
                        guest.force_attr = guest_cfg.force
                    if guest_cfg.intellect is not None:
                        guest.intellect_attr = guest_cfg.intellect
                    if guest_cfg.defense is not None:
                        guest.defense = guest_cfg.defense
                    if guest_cfg.agility is not None:
                        guest.agility = guest_cfg.agility
                    if guest_cfg.luck is not None:
                        guest.luck = guest_cfg.luck

                    # 重新计算攻击力
                    guest.attack = self._calculate_attack(guest)
                    guest.max_hp = self._calculate_hp(guest)
                    guest.hp = guest.max_hp

                    guest_combatants.append(guest)

        # 构造小兵
        if party_cfg.troops:
            templates = load_troop_templates()

            # 构造科技效果
            tech_effects = self._build_tech_effects(party_cfg)

            for troop_key, count in party_cfg.troops.items():
                template = next((t for t in templates if t.key == troop_key), None)
                if not template:
                    continue

                troop_units = build_troop_combatants(
                    troops={troop_key: count},
                    templates=templates,
                    tech_effects=tech_effects,
                    side=side
                )
                troop_combatants.extend(troop_units)

        return guest_combatants, troop_combatants

    def _calculate_attack(self, guest) -> int:
        """根据门客类型计算攻击力"""
        archetype = getattr(guest, "archetype", "military")
        if archetype == "civil":
            return int(guest.force_attr * 0.4 + guest.intellect_attr * 0.6)
        else:
            return int(guest.force_attr * 0.7 + guest.intellect_attr * 0.3)

    def _calculate_hp(self, guest) -> int:
        """计算门客HP"""
        base_hp = getattr(guest, "template_base_hp", 2400)
        defense = guest.defense
        return int(base_hp + defense * 50)

    def _build_tech_effects(self, party_cfg: PartyConfig) -> Dict[str, Any]:
        """构造科技效果"""
        from gameplay.services.technology import get_troop_stat_bonuses

        # 使用统一等级或精细等级
        if party_cfg.technology_levels:
            tech_levels = party_cfg.technology_levels
        else:
            level = party_cfg.technology_level
            tech_levels = {
                f"{troop_class}_{stat}": level
                for troop_class in ["dao", "qiang", "jian", "quan", "gong"]
                for stat in ["attack", "defense", "hp", "speed"]
            }

        return get_troop_stat_bonuses(tech_levels)
```

---

### 6.3 运行模拟

```python
class BattleSimulator:
    def run_battle(self, seed: int = None) -> dict:
        """运行战斗模拟"""
        from battle.simulation_core import simulate_battle, build_rng

        # 构造双方
        attacker_guests, attacker_troops = self.build_party(
            self.config.attacker, "attacker"
        )
        defender_guests, defender_troops = self.build_party(
            self.config.defender, "defender"
        )

        # 合并单位
        attacker_units = attacker_guests + attacker_troops
        defender_units = defender_guests + defender_troops

        # 生成RNG
        actual_seed, rng = build_rng(seed)

        # 参数覆盖上下文
        with patch_battle_params(self.config.tunable_params):
            result = simulate_battle(
                attacker_units=attacker_units,
                defender_units=defender_units,
                rng=rng,
                seed=actual_seed,
                travel_seconds=None,
                config={},  # 不需要loot配置
                drop_table=None
            )

        return {
            "seed": actual_seed,
            "winner": result.winner,
            "rounds": result.rounds,
            "losses": result.losses,
            "drops": result.drops,
            "combat_log": result.rounds  # 详细战斗日志
        }
```

---

## 七、输出格式

### 7.1 简要模式（默认）

```
═══════════════════════════════════════════════════
战斗模拟结果
═══════════════════════════════════════════════════
配置: balanced (平衡配置测试)
种子: 123456
───────────────────────────────────────────────────
胜者: attacker
回合: 3
攻方兵损: 120 / 500 (24.0%)
守方兵损: 2000 / 2000 (100.0%)
攻方HP损失: 18.5%
守方HP损失: 100.0%
═══════════════════════════════════════════════════

技能触发统计:
  龙吟破阵: 2次
  奇策突袭: 1次
```

### 7.2 详细模式（--verbose）

```
═══════════════════════════════════════════════════
战斗开始 (seed: 123456)
配置: balanced
═══════════════════════════════════════════════════

攻方阵容:
  门客:
    [Lv100] 独孤求败 (攻:440 防:300 HP:17400)
    [Lv80]  无名     (攻:380 防:250 HP:14900)
  小兵:
    刀圣 ×200 (攻:20 防:9 HP:60)
    弓神 ×300 (攻:18 防:6 HP:45)

守方阵容:
  小兵:
    枪圣 ×2000 (攻:18 防:10 HP:70, 科技Lv10)

───────────────────────────────────────────────────
━━━ 回合 1 (先锋阶段, 优先级-2) ━━━
[#1] 弓神(攻方) → 枪圣(守方)
     伤害: 1850 | 击杀: 138 | 暴击 | 远程攻击
     剩余: 1862

[#2] 弓神(攻方) → 枪圣(守方)
     伤害: 1720 | 击杀: 128
     剩余: 1734

━━━ 回合 1 (先攻阶段, 优先级-1) ━━━
[#3] 独孤求败(攻方) → 枪圣(守方)
     伤害: 850 | 击杀: 1043 | 技能:[龙吟破阵] ×3目标
     剩余: 691

[#4] 无名(攻方) → 枪圣(守方)
     伤害: 720 | 击杀: 884 | 技能:[奇策突袭]
     └─ 枪圣 被眩晕 (1回合)
     剩余: 0 ✗ 全灭

━━━ 战斗结束 ━━━
═══════════════════════════════════════════════════
胜者: attacker
总回合: 1 (含先攻阶段)
总伤害: 5,140
总击杀: 2,193
═══════════════════════════════════════════════════

最终状态:
攻方存活:
  独孤求败: 17400/17400 HP (100%)
  无名:     14900/14900 HP (100%)
  刀圣:     200/200
  弓神:     300/300

守方存活:
  (全灭)
```

### 7.3 CSV导出

```csv
config_name,seed,winner,rounds,attacker_troops_lost,defender_troops_lost,attacker_hp_loss_percent,defender_hp_loss_percent,dragon_roar_triggers,stratagem_burst_triggers
balanced,123456,attacker,3,120,2000,18.5,100.0,2,1
balanced,123457,attacker,3,115,2000,17.2,100.0,1,2
balanced,123458,attacker,2,98,2000,15.8,100.0,3,1
```

### 7.4 JSON导出

```json
{
  "config": {
    "name": "balanced",
    "description": "平衡配置测试"
  },
  "simulation": {
    "seed": 123456,
    "params": {
      "slaughter_multiplier": 30,
      "troop_attack_divisor_vs_guest": 4.0
    }
  },
  "result": {
    "winner": "attacker",
    "rounds": 3,
    "losses": {
      "attacker": {
        "troops_lost": 120,
        "hp_loss_percent": 18.5
      },
      "defender": {
        "troops_lost": 2000,
        "hp_loss_percent": 100.0
      }
    },
    "skills": {
      "dragon_roar": 2,
      "stratagem_burst": 1
    }
  },
  "combat_log": [
    {
      "round": 1,
      "priority": -2,
      "events": [...]
    }
  ]
}
```

---

## 八、实施计划

### 阶段1：核心框架（1-2天）

- [ ] 创建目录结构
- [ ] 实现配置加载器（config.py）
- [ ] 实现基础CLI（cli.py）
- [ ] 实现参数覆盖机制（simulator.py）
- [ ] 测试单次模拟

### 阶段2：分析与报告（1天）

- [ ] 实现指标提取（analyzer.py）
- [ ] 实现表格输出（reporter.py）
- [ ] 实现CSV/JSON导出
- [ ] 测试输出格式

### 阶段3：调优功能（1-2天）

- [ ] 实现网格搜索（tuner.py）
- [ ] 实现区间扫描
- [ ] 实现配置对比
- [ ] 测试调优功能

### 阶段4：预设与文档（1天）

- [ ] 创建预设配置（4-5个）
- [ ] 编写使用文档
- [ ] 添加示例场景
- [ ] 完成测试

### 总计：4-6天

---

## 附录：扩展功能

### A.1 图表可视化

```python
# 可选：使用matplotlib生成图表
def plot_tuning_results(tuning_result: TuningResult, output_file: str):
    """绘制调参结果曲线"""
    import matplotlib.pyplot as plt

    params = [r["slaughter_multiplier"] for r in tuning_result.param_combinations]
    rounds = [m.rounds for m in tuning_result.metrics_list]
    losses = [m.attacker_troops_lost for m in tuning_result.metrics_list]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot(params, rounds, marker='o')
    ax1.set_xlabel('Slaughter Multiplier')
    ax1.set_ylabel('Rounds')
    ax1.set_title('Rounds vs Slaughter Multiplier')

    ax2.plot(params, losses, marker='o', color='red')
    ax2.set_xlabel('Slaughter Multiplier')
    ax2.set_ylabel('Attacker Troops Lost')
    ax2.set_title('Losses vs Slaughter Multiplier')

    plt.tight_layout()
    plt.savefig(output_file)
    print(f"图表已保存: {output_file}")
```

### A.2 Web界面

```python
# 可选：Django Admin集成
class BattleDebuggerAdmin(admin.ModelAdmin):
    """在Django Admin中提供调试界面"""

    def run_simulation(self, request):
        # 表单提交 → 运行模拟 → 显示结果
        pass
```

---

## 结语

这个设计提供了一个**完整、灵活、易用**的战斗调试工具，可以：

✅ 快速测试不同配置
✅ 动态调整参数而不改代码
✅ 批量对比和调优
✅ 清晰展示战斗过程
✅ 导出数据用于进一步分析

**下一步**：开始实现阶段1，搭建核心框架。
