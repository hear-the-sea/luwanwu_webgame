# Gameplay Services 模块组织

## 推荐用法（推荐）

```python
# 直接从子模块导入，更清晰
from gameplay.services.manor import ensure_manor
from gameplay.services.resources import grant_resources
from gameplay.services.inventory import add_item_to_inventory
```

## 向后兼容用法

```python
# 从主模块导入（保持向后兼容）
from gameplay.services import ensure_manor, grant_resources
```

## 模块列表

### 核心模块
- `building.py`: 建筑配置加载（YAML）
- `manor.py`: 庄园核心管理
- `resources.py`: 资源管理
- `inventory/`: 背包物品管理（模块包）
- `messages.py`: 消息系统
- `missions.py`: 任务系统
- `technology.py`: 技术研究
- `notifications.py`: WebSocket通知封装
- `template_cache.py`: 模板缓存统一管理

### 生产模块
- `smithy.py`: 冶炼坊服务
- `forge.py`: 铁匠铺服务
- `ranch.py`: 畜牧场服务
- `stable.py`: 马房服务

### 其他模块
- `prestige.py`: 声望系统
- `cache.py`: 缓存工具
- `query_optimization.py`: 查询优化工具
- `troops.py`: 护院管理

## 最佳实践

### 1. 导入风格
推荐使用绝对导入而非相对导入：
```python
# ✅ 推荐：绝对导入
from gameplay.services.manor import ensure_manor
from gameplay.services.resources import grant_resources

# ❌ 避免：相对导入
from ..services.manor import ensure_manor
```

### 2. WebSocket 通知
统一使用 `notifications.py` 中的 `notify_user()` 函数：
```python
from gameplay.services.notifications import notify_user

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
使用 `template_cache.py` 中的缓存工具：
```python
from gameplay.services.template_cache import get_template_cache

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
# 旧代码
from gameplay.services import ensure_manor

# 新代码
from gameplay.services.manor import ensure_manor
```

## 注意事项

1. **向后兼容**: 主模块 `__init__.py` 仍然导出所有公共函数，保持向后兼容
2. **性能差异**: 两种导入方式在性能上没有显著差异
3. **IDE支持**: 直接从子模块导入可以获得更好的IDE自动补全和类型推断
