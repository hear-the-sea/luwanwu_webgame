# 运行期配置与数据文件

本文档说明项目中 `data/` 目录下 YAML 文件的用途、加载方式，以及修改后的生效方式。

## 两类 YAML

### 1. 运行期自动读取配置

这类 YAML 由 Python 服务直接读取，通常带进程内缓存。
修改后 **不需要导入数据库**，但需要 **重启进程** 或执行：

```bash
python manage.py reload_runtime_configs
```

当前已纳入统一刷新命令的文件：

- `data/arena_rewards.yaml`
- `data/arena_rules.yaml`
- `data/forge_blueprints.yaml`
- `data/forge_decompose.yaml`
- `data/forge_equipment.yaml`
- `data/guest_growth_rules.yaml`
- `data/guild_rules.yaml`
- `data/ranch_production.yaml`
- `data/smithy_production.yaml`
- `data/stable_production.yaml`
- `data/trade_market_rules.yaml`
- `data/warehouse_production.yaml`
- 商铺 / 拍卖相关配置文件（通过对应 service loader 刷新）

### 2. 需要导入数据库的内容配置

这类 YAML 不会直接被业务服务实时读取，而是通过 management command 导入数据库。
修改后需要执行对应命令，或执行：

```bash
python manage.py bootstrap_game_data
```

典型文件：

- `data/building_templates.yaml`
- `data/technology_templates.yaml`
- `data/item_templates.yaml`
- `data/troop_templates.yaml`
- `data/guest_templates.yaml`
- `data/guest_skills.yaml`
- `data/mission_templates.yaml`

## 推荐操作方式

### 修改运行期配置后

```bash
python manage.py reload_runtime_configs
```

适合：

- 锻造/冶炼/马匹/养殖配方调整
- 竞技场规则调整
- 帮会数值规则调整
- 交易行挂单档位调整
- 门客全局成长默认值调整
- 仓库产出规则调整

### 修改模板数据后

```bash
python manage.py bootstrap_game_data --skip-images
```

适合：

- 建筑、科技、物品、门客、兵种、任务模板变更

## 部署建议

- 发布时应确保代码与 `data/*.yaml` 同步部署。
- 如果改动仅涉及运行期自动读取配置，部署后执行一次 `python manage.py reload_runtime_configs` 即可。
- 如果改动涉及数据库模板数据，部署后执行对应导入命令，或统一执行 `python manage.py bootstrap_game_data --skip-images`。
- 对于 Web / Worker 分离部署，最稳妥做法仍然是：刷新配置后重启相关进程，避免旧进程保留旧缓存。
