"""
掉落奖励生成工具模块

该工具属于跨 app 的纯逻辑（battle/gameplay 都会用到），实现迁移到 `common.utils.loot`。
本模块保留以保持向后兼容的导入路径。
"""

from __future__ import annotations

from common.utils.loot import resolve_drop_rewards

__all__ = ["resolve_drop_rewards"]
