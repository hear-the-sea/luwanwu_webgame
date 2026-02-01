from __future__ import annotations


class TimeConstants:
    """Shared time-related constants (seconds)."""

    MINUTE = 60
    HOUR = 3600
    DAY = 86400

    # gameplay
    RESOURCE_UPDATE_INTERVAL = 60  # 1分钟
    TASK_CHECK_INTERVAL = 60  # 任务检查间隔

    # guests
    HP_RECOVERY_INTERVAL = 600  # 10分钟更新一次
    HP_FULL_RECOVERY_TIME = 24 * 3600  # 24小时完全恢复
    TRAINING_CHECK_INTERVAL = 60  # 训练检查间隔
