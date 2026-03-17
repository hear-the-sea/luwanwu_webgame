# Gameplay Services 模块组织

## 推荐用法（推荐）

```python
# 直接从子模块导入，更清晰
from gameplay.services.manor.core import ensure_manor
from gameplay.services.resources import grant_resources
from gameplay.services.inventory.core import add_item_to_inventory
```

## 模块列表

### 核心模块
- `manor/core.py`: 庄园核心管理
- `manor/prestige.py`: 声望系统
- `manor/treasury.py`: 藏宝阁服务
- `resources.py`: 资源管理
- `inventory/`: 背包物品管理（模块包）
- `technology.py`: 技术研究

### 建筑模块 (`buildings/`)
- `buildings/base.py`: 建筑配置加载（YAML）
- `buildings/forge.py`: 铁匠铺服务
- `buildings/smithy.py`: 冶炼坊服务
- `buildings/ranch.py`: 畜牧场服务
- `buildings/stable.py`: 马房服务

### 招募模块 (`recruitment/`)
- `recruitment/recruitment.py`: 护院募兵服务
- `recruitment/troops.py`: 护院管理

### 工具模块 (`utils/`)
- `utils/cache.py`: 缓存工具
- `utils/messages.py`: 消息系统
- `utils/notifications.py`: WebSocket通知封装
- `utils/query_optimization.py`: 查询优化工具
- `utils/template_cache.py`: 模板缓存统一管理

## 最佳实践

### 1. 导入风格
推荐使用绝对导入而非相对导入：
```python
# ✅ 推荐：绝对导入
from gameplay.services.manor.core import ensure_manor
from gameplay.services.resources import grant_resources

# ❌ 避免：相对导入
from ..services.manor import ensure_manor
```

### 2. WebSocket 通知
统一使用 `utils/notifications.py` 中的 `notify_user()` 函数：
```python
from gameplay.services.utils.notifications import notify_user

notify_user(
    user_id=manor.user_id,
    payload={
        "kind": "system",
        "title": "操作完成",
    },
    log_context="operation notification",
)
```

### 3. 模板缓存
使用 `utils/template_cache.py` 中的缓存工具：
```python
from gameplay.services.utils.template_cache import clear_all_template_caches

# 获取缓存的模板数据
templates = get_template_cache()
```

### 4. 资源操作
使用 `resources.py` 中的函数进行资源操作：
```python
from gameplay.services.resources import grant_resources, spend_resources

# 发放资源
grant_resources(manor, {"silver": 1000}, note="任务奖励")

# 消耗资源
spend_resources(manor, {"silver": 500}, note="购买物品")
```

## 迁移指南

如果需要从旧代码迁移到新的导入风格：

1. 找到所有从 `gameplay.services` 导入的代码
2. 将导入改为从具体子模块导入
3. 验证功能是否正常

示例：
```python
# 推荐代码
from gameplay.services.manor.core import ensure_manor
```

## 注意事项

1. **聚合入口收缩**: `gameplay.services` 保留模块级入口，不再承诺继续直出各域函数
2. **推荐风格**: 直接从子模块导入可以获得更好的IDE自动补全和类型推断
3. **迁移原则**: 仓内代码优先使用具体子模块，而不是继续扩展总聚合入口
