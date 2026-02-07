"""任务管理服务（兼容层）。

注意：不要把 `gameplay.services.missions` 变成 package（目录），否则
`from gameplay.services import missions` 和 Django/mypy 插件的加载路径会发生变化。
"""

from __future__ import annotations

from .missions_facade import *  # noqa: F401,F403
from .missions_facade import __all__  # noqa: F401
