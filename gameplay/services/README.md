# Gameplay Services 模块说明

> 最近校正：2026-03-26

`gameplay.services` 现在已经不再是“所有玩法函数的聚合导出层”，而是一个按领域拆分的服务包。仓内新代码应直接从具体子模块导入，而不是继续往包根部堆导出。

## 当前目录事实

主要子域如下：

- `manor/`：庄园初始化、刷新、命名、藏宝阁、护院库等
- `inventory/`：背包、使用物品、门客道具、随机源
- `buildings/`：锻造、冶炼、养殖、马房及其运行期配置
- `recruitment/`：募兵生命周期、模板与查询
- `arena/`：报名、轮次、奖励、快照、规则
- `raid/`：地图搜索、侦查、踢馆保护、刷新与返回
- `missions_impl/`：任务发起、刷新、撤退、结算、补偿
- `utils/`：缓存、消息、通知、模板缓存、查询优化

仍保留在包根部的单文件服务主要是：

- `resources.py`
- `technology.py`
- `work.py`
- `jail.py`
- `chat.py`
- `global_mail.py`
- `runtime_configs.py`

## 推荐导入方式

推荐：

```python
from gameplay.services.manor.bootstrap import ensure_manor
from gameplay.services.inventory.core import add_item_to_inventory
from gameplay.services.raid.scout import start_scout
from gameplay.services.missions_impl.launch_command import launch_mission
```

避免：

```python
from gameplay.services import ensure_manor
from gameplay.services import launch_mission
```

原因：

- 包根不再承诺稳定 re-export
- 直接导入具体模块更利于类型检查、IDE 跳转和重构
- 可以更准确地表达依赖的业务域

## 当前协作约束

### 1. 读写路径分离优先

- 页面上下文装配优先放在 `selectors/`
- 写状态机、事务边界和补偿逻辑优先放在 `services/`

### 2. 并发敏感逻辑不要回退到 view

以下类型的逻辑应继续保留在 service / task：

- 任务、侦查、踢馆、招募等状态机推进
- 资源扣减与发奖
- `select_for_update()` 互斥
- `transaction.on_commit(...)` 后置动作

### 3. 运行期 YAML 刷新走统一入口

需要刷新商铺、拍卖、竞技场、生产等规则时，使用：

```bash
python manage.py reload_runtime_configs
```

不要在调用方自己零散清理缓存，除非当前文件明确未纳入统一刷新口径。

### 4. 通知与消息尽量复用现有封装

- 站内消息：优先复用 `gameplay.services.utils.messages`
- WebSocket 推送：优先复用 `gameplay.services.utils.notifications`
- 不要在业务函数里手写 channel layer 细节，除非是在扩展底层能力

## 迁移建议

如果你在清理旧代码：

1. 先把 `from gameplay.services import ...` 改成具体子模块导入
2. 再看该逻辑是更像读侧、写侧还是运行期配置
3. 如果逻辑已经膨胀，优先按领域拆进对应子目录，而不是新增一个新的“万能 services.py”

## 与其他文档的关系

- 写路径边界：[`docs/write_model_boundaries.md`](/home/daniel/code/web_game_v5/docs/write_model_boundaries.md)
- 数据流边界：[`docs/domain_boundaries.md`](/home/daniel/code/web_game_v5/docs/domain_boundaries.md)
- 开发命令与刷新方式：[`docs/development.md`](/home/daniel/code/web_game_v5/docs/development.md)
