# 技术系统实现计划

## 需求概述

添加技术页面，包含三个子页面：基本技术、武艺技术、生产技术。

## 技术分类

### 1. 基本技术
| 技术名称 | 功能 | 效果 |
|---------|------|------|
| 侦查术 | 提高探子侦察和反侦察能力 | 每级+10% |
| 行军术 | 提高所有部队移动速度 | 每级+10% |
| 建筑学 | 减少建筑建造成本 | 每级-5% |

### 2. 武艺技术（5类兵种 × 6项技术 = 30项）

**刀类**：力劈华山(武力)、横炼铁杉(防御)、疾风碎步(敏捷)、蓄日回元(生命)、破甲一击(对剑系)、狂狼必杀(双倍打击)

**枪类**：破日枪法(武力)、金钟罡气(防御)、乾坤挪移(敏捷)、体血倍增(生命)、攻坚破城(对建筑)、反戈一击(反击)

**剑类**：长虹贯日(武力)、纯阳护体(防御)、飘絮身法(敏捷)、回春转气(生命)、护身剑罡(反弹)、驭剑之术(先攻)

**拳类**：通背神拳(武力)、金钟罩体(防御)、凌波渡虚(敏捷)、炼气回元(生命)、万宗归流(对远程防御)、五气朝元(恢复)

**弓箭**：百步穿杨(武力)、天地反转(防御)、御风追月(敏捷)、云流转气(生命)、凤舞九天(射程+1)、短刃杀法(近战)

### 3. 生产技术
| 技术名称 | 功能 | 效果 |
|---------|------|------|
| 农耕术 | 增加粮食产量 | 每级+5%，满级(30级)+150% |
| 刀兵招募 | 减少刀类兵种招募成本 | 每级-5% |
| 枪兵招募 | 减少枪类兵种招募成本 | 每级-5% |
| 剑士招募 | 减少剑类兵种招募成本 | 每级-5% |
| 拳师招募 | 减少拳类兵种招募成本 | 每级-5% |
| 弓手招募 | 减少弓箭类兵种招募成本 | 每级-5% |

---

## 实现步骤

### 第一阶段：数据层

1. **创建技术配置文件** `data/technology_templates.yaml`
   - 定义所有技术的 key、名称、描述、分类、效果类型、效果值

2. **创建数据模型** `gameplay/models.py`
   ```python
   class PlayerTechnology(models.Model):
       manor = models.ForeignKey(Manor, on_delete=models.CASCADE, related_name="technologies")
       tech_key = models.CharField(max_length=64)
       level = models.PositiveIntegerField(default=0)
   ```

3. **创建技术服务** `gameplay/services/technology.py`
   - `load_technology_templates()`: 加载技术配置
   - `get_player_technologies(manor)`: 获取玩家技术等级
   - `upgrade_technology(manor, tech_key)`: 升级技术
   - `get_tech_bonus(manor, tech_key)`: 获取技术加成值

### 第二阶段：页面层

4. **创建视图** `gameplay/views.py`
   - `TechnologyView`: 技术主页面，支持 tab 参数切换子页面

5. **创建模板** `gameplay/templates/gameplay/technology.html`
   - 三个 tab：基本技术、武艺技术、生产技术
   - 每个技术卡片显示：名称、描述、当前等级、升级成本、升级按钮

6. **注册路由** `gameplay/urls.py`
   - `path("technology/", TechnologyView.as_view(), name="technology")`
   - `path("technology/upgrade/<str:tech_key>/", upgrade_technology_view, name="upgrade_technology")`

7. **添加导航链接** `templates/base.html`
   - 在导航栏添加"技术"链接

### 第三阶段：效果应用

8. **行军术效果** `gameplay/utils/resource_calculator.py`
   - 在 `calculate_travel_time()` 中应用行军术加成

9. **建筑学效果** `gameplay/models.py`
   - 在 `Building.next_level_cost()` 中应用建筑学减免

10. **武艺技术效果** `battle/combatants.py`
    - 在 `build_troop_combatants()` 中应用兵种属性加成
    - 新增战斗特效处理（双倍打击、反击、反弹等）

11. **生产技术效果** `gameplay/services.py`
    - 在资源产出计算中应用产量加成

---

## 文件清单

| 操作 | 文件路径 |
|------|----------|
| 新增 | `data/technology_templates.yaml` |
| 修改 | `gameplay/models.py` - 添加 PlayerTechnology 模型 |
| 新增 | `gameplay/services/technology.py` |
| 修改 | `gameplay/views.py` - 添加 TechnologyView |
| 新增 | `gameplay/templates/gameplay/technology.html` |
| 修改 | `gameplay/urls.py` - 添加路由 |
| 修改 | `templates/base.html` - 添加导航链接 |
| 修改 | `gameplay/utils/resource_calculator.py` - 应用行军术 |
| 修改 | `battle/combatants.py` - 应用武艺技术 |

---

## 升级成本设计

技术升级消耗银两，成本随等级递增：
- 等级 1: 100 银两
- 等级 2: 200 银两
- 等级 3: 400 银两
- ...
- 公式: `cost = base_cost * (2 ^ (level - 1))`

最高等级：10 级
