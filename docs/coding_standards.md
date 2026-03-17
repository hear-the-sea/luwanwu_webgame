# 导入风格规范

## 原则

使用**绝对导入**（absolute imports），避免**相对导入**（relative imports）。

## 示例

### ✅ 推荐：绝对导入

```python
# 从项目根目录开始的完整导入路径
from gameplay.services.manor.core import ensure_manor
from core.exceptions import GuestCapacityFullError
from guests.services.recruitment import recruit_guest
```

### ❌ 避免：相对导入

```python
# 使用相对点的导入
from ..services.manor.core import ensure_manor
from ....core.exceptions import GuestCapacityFullError
from .recruitment import recruit_guest
```

## 理由

1. **清晰性**: 绝对导入明确显示模块的完整路径，更容易理解代码结构
2. **可维护性**: 避免重构时路径变更问题，减少因移动文件导致的导入错误
3. **IDE支持**: 现代IDE工具对绝对导入的支持更好，提供更准确的自动补全和跳转
4. **Python最佳实践**: 符合PEP 8推荐的导入风格
5. **调试友好**: 错误堆栈中的模块路径更清晰，便于调试

## 特殊情况

### 同级模块导入

即使在同一目录下，也推荐使用绝对导入：

```python
# ✅ 推荐
from gameplay.services.resources import grant_resources

# ❌ 避免
from .resources import grant_resources
```

### 包内部导入

对于包内部的模块，仍然使用绝对导入：

```python
# ✅ 推荐
from gameplay.services.inventory.core import add_item_to_inventory

# ❌ 避免
from ..inventory import add_item_to_inventory
```

### __init__.py 文件

在 `__init__.py` 文件中，不要继续扩展函数级聚合导出：

```python
# gameplay/services/__init__.py
"""Import concrete submodules instead of re-exporting service functions."""
```

新代码直接使用具体子模块：

```python
# gameplay/services/__init__.py
from gameplay.services.manor.core import ensure_manor
from gameplay.services.resources import grant_resources
```

## 自动化工具

### 检查相对导入

使用以下命令查找所有相对导入：

```bash
grep -rn "from \.\." --include="*.py" . | grep -v "migrations/"
grep -rn "from \." --include="*.py" . | grep -v "migrations/" | grep -v "from \.\.\."
```

### 自动修复

使用 `pyupgrade` 工具自动修复导入风格：

```bash
# 安装 pyupgrade
pip install pyupgrade

# 自动转换为绝对导入
pyupgrade --py3-plus --keep-percent-format gameplay/ guests/ trade/ guilds/ battle/
```

## 迁移步骤

如果需要将现有代码从相对导入迁移到绝对导入：

1. **识别相对导入**: 使用上述 grep 命令查找所有相对导入
2. **确定绝对路径**: 根据文件位置确定完整的导入路径
3. **替换导入**: 将相对导入替换为绝对导入
4. **测试验证**: 运行测试确保功能正常

示例迁移：

```python
# 文件：gameplay/views/building.py
# 旧代码
from ..services.manor import ensure_manor

# 新代码
from gameplay.services.manor.core import ensure_manor
```

## 注意事项

1. **不要修改 migrations 文件**: Django 的 migrations 文件应该保持原样
2. **收缩 __init__.py**: `__init__.py` 应保持轻量，不再承担函数级兼容导出
3. **逐步迁移**: 可以逐步迁移，不必一次性修改所有文件
4. **测试覆盖**: 每次迁移后都要运行测试确保功能正常

## 参考资料

- [PEP 8 - Imports](https://peps.python.org/pep-0008/#imports)
- [Python Imports: Absolute vs. Relative](https://realpython.com/absolute-vs-relative-python-imports/)

## 项目统计

根据代码库扫描：

- **绝对导入**: 382个文件（主流）
- **相对导入**: 20个文件
- **混合使用**: 少数文件

我们的目标是：**100% 使用绝对导入**
