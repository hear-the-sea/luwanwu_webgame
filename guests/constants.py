"""
门客系统相关常量
"""


# 时间常量（秒）
class TimeConstants:
    """时间相关常量"""

    MINUTE = 60
    HOUR = 3600
    DAY = 86400

    # 生命值恢复
    HP_RECOVERY_INTERVAL = 600  # 10分钟更新一次
    HP_FULL_RECOVERY_TIME = 24 * 3600  # 24小时完全恢复

    # 训练时间
    TRAINING_CHECK_INTERVAL = 60  # 训练检查间隔


# 门客状态
class GuestStatus:
    """门客状态常量"""

    IDLE = "idle"  # 空闲
    ON_MISSION = "on_mission"  # 执行任务中
    TRAINING = "training"  # 训练中
    INJURED = "injured"  # 受伤
    RESTING = "resting"  # 休息


# 装备槽位
class EquipmentSlots:
    """装备槽位常量"""

    WEAPON = "weapon"  # 武器
    ARMOR = "armor"  # 护甲
    ACCESSORY = "accessory"  # 饰品
    MOUNT = "mount"  # 坐骑


# 门客品质
class GuestRarity:
    """门客品质常量"""

    COMMON = 1  # 普通
    UNCOMMON = 2  # 优秀
    RARE = 3  # 精良
    EPIC = 4  # 史诗
    LEGENDARY = 5  # 传说


# 招募相关
class RecruitmentConstants:
    """招募相关常量"""

    # 卡池类型
    POOL_NORMAL = "normal"  # 普通卡池
    POOL_ADVANCED = "advanced"  # 高级卡池
    POOL_PREMIUM = "premium"  # 至尊卡池

    # 抽卡消耗
    NORMAL_COST_GOLD = 100
    ADVANCED_COST_GOLD = 500
    PREMIUM_COST_GOLD = 1000


# 训练相关
class TrainingConstants:
    """训练相关常量"""

    # 训练类型
    TRAINING_STRENGTH = "strength"  # 力量训练
    TRAINING_INTELLIGENCE = "intelligence"  # 智力训练
    TRAINING_AGILITY = "agility"  # 敏捷训练
    TRAINING_CHARM = "charm"  # 魅力训练

    # 训练效果
    BASE_TRAINING_GAIN = 1  # 基础训练收益


# 生命值相关
class HealthConstants:
    """生命值相关常量"""

    MIN_HP_PERCENT = 0  # 最低生命值百分比
    MAX_HP_PERCENT = 100  # 最高生命值百分比
    CRITICAL_HP_THRESHOLD = 20  # 危急生命值阈值（%）
