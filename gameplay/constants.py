"""
游戏玩法相关常量
"""

from common.constants.resources import ResourceType, ResourceTypes  # noqa: F401
from common.constants.time import TimeConstants  # noqa: F401
from core.config import BUILDING_KEYS

# 为了向后兼容，重新导出 BuildingKeys
BuildingKeys = BUILDING_KEYS

# 建筑最高等级限制（未配置则无限制）
BUILDING_MAX_LEVELS = {
    # 特殊建筑
    BUILDING_KEYS.CITANG: 5,  # 祠堂：避免缩时达到100%
    BUILDING_KEYS.YOUXIA_BAOTA: 15,  # 悠嘻宝塔：出战上限在15级封顶（SQUAD_SIZE_MAX=18）
    BUILDING_KEYS.TREASURY: 20,  # 藏宝阁：容量函数按20级封顶（平衡时间消耗）
    BUILDING_KEYS.JAIL: 5,  # 监牢：满级5人
    BUILDING_KEYS.OATH_GROVE: 5,  # 结义林：满级5人
    # 仓储设施
    BUILDING_KEYS.SILVER_VAULT: 30,  # 银库：满级4000万两
    BUILDING_KEYS.GRANARY: 20,  # 粮仓：满级1050万石
    # 资源产出建筑
    BUILDING_KEYS.BATHHOUSE: 20,  # 澡堂：满级每小时产银1000两+门客回血200%
    BUILDING_KEYS.LATRINE: 20,  # 茅厕：满级每小时产粮1000+产银1000两
    BUILDING_KEYS.TAVERN: 10,  # 酒馆：满级每小时产银1000两+候选人数+10
    "farm": 50,  # 农田：满级50级
    "tax_office": 20,  # 税务司：满级20级
    # 人员管理建筑
    BUILDING_KEYS.JUXIAN_ZHUANG: 15,  # 聚贤庄：满级容量18位门客
    BUILDING_KEYS.JIADING_FANG: 30,  # 家丁房：满级容量3050个位置
    BUILDING_KEYS.LIANGGONG_CHANG: 10,  # 练功场：满级护院训练速度提升30%
    # 生产加工建筑
    BUILDING_KEYS.RANCH: 10,  # 畜牧场：满级家畜制造速度提升50%
    BUILDING_KEYS.SMITHY: 10,  # 冶炼坊：满级物资制造速度提升50%
    BUILDING_KEYS.STABLE: 10,  # 马房：满级马匹制造速度提升50%
    # 战斗相关建筑
    BUILDING_KEYS.LIANBING_DAYING: 10,  # 练兵大营：满级护院训练速度提升50%
    BUILDING_KEYS.FORGE: 10,  # 铁匠铺：满级装备制造速度提升50%
}


# 建筑最高等级限制（未配置则无限制）
BUILDING_MAX_LEVELS = {
    # 特殊建筑
    BuildingKeys.CITANG: 5,  # 祠堂：避免缩时达到100%
    BuildingKeys.YOUXIA_BAOTA: 15,  # 悠嘻宝塔：出战上限在15级封顶（SQUAD_SIZE_MAX=18）
    BuildingKeys.TREASURY: 20,  # 藏宝阁：容量函数按20级封顶（平衡时间消耗）
    BuildingKeys.JAIL: 5,  # 监牢：满级5人
    BuildingKeys.OATH_GROVE: 5,  # 结义林：满级5人
    # 仓储设施
    BuildingKeys.SILVER_VAULT: 30,  # 银库：满级4000万两
    BuildingKeys.GRANARY: 20,  # 粮仓：满级1050万石
    # 资源产出建筑
    BuildingKeys.BATHHOUSE: 20,  # 澡堂：满级每小时产银1000两+门客回血200%
    BuildingKeys.LATRINE: 20,  # 茅厕：满级每小时产粮1000+产银1000两
    BuildingKeys.TAVERN: 10,  # 酒馆：满级每小时产银1000两+候选人数+10
    "farm": 50,  # 农田：满级50级
    "tax_office": 20,  # 税务司：满级20级
    # 人员管理建筑
    BuildingKeys.JUXIAN_ZHUANG: 15,  # 聚贤庄：满级容量18位门客
    BuildingKeys.JIADING_FANG: 30,  # 家丁房：满级容量3050个位置
    BuildingKeys.LIANGGONG_CHANG: 10,  # 练功场：满级护院训练速度提升30%
    # 生产加工建筑
    BuildingKeys.RANCH: 10,  # 畜牧场：满级家畜制造速度提升50%
    BuildingKeys.SMITHY: 10,  # 冶炼坊：满级物资制造速度提升50%
    BuildingKeys.STABLE: 10,  # 马房：满级马匹制造速度提升50%
    BuildingKeys.FORGE: 10,  # 铁匠铺：满级装备锻造速度提升50%
}

# 同时升级限制
# 注意：当前系统允许建筑/科技分别并行升级，此处限制为“同类队列”的并发上限。
MAX_CONCURRENT_BUILDING_UPGRADES = 2
MAX_CONCURRENT_TECH_UPGRADES = 2


# 资源类型
# 游戏平衡参数
class GameBalance:
    """游戏平衡参数"""

    # 基础资源产量
    BASE_GRAIN_PRODUCTION = 100  # 每小时
    BASE_SILVER_PRODUCTION = 50

    # 初始资源
    INITIAL_GRAIN = 1200
    INITIAL_SILVER = 500


# ============ 地区系统常量 ============

REGION_CHOICES = [
    # 直辖市
    ("beijing", "北京"),
    ("tianjin", "天津"),
    ("shanghai", "上海"),
    ("chongqing", "重庆"),
    # 华北
    ("hebei", "河北"),
    ("shanxi", "山西"),
    ("neimenggu", "内蒙古"),
    # 东北
    ("liaoning", "辽宁"),
    ("jilin", "吉林"),
    ("heilongjiang", "黑龙江"),
    # 华东
    ("jiangsu", "江苏"),
    ("zhejiang", "浙江"),
    ("anhui", "安徽"),
    ("fujian", "福建"),
    ("jiangxi", "江西"),
    ("shandong", "山东"),
    # 华中
    ("henan", "河南"),
    ("hubei", "湖北"),
    ("hunan", "湖南"),
    # 华南
    ("guangdong", "广东"),
    ("guangxi", "广西"),
    ("hainan", "海南"),
    # 西南
    ("sichuan", "四川"),
    ("guizhou", "贵州"),
    ("yunnan", "云南"),
    ("xizang", "西藏"),
    # 西北
    ("shaanxi", "陕西"),
    ("gansu", "甘肃"),
    ("qinghai", "青海"),
    ("ningxia", "宁夏"),
    ("xinjiang", "新疆"),
    # 特别行政区
    ("hongkong", "香港"),
    ("macao", "澳门"),
    ("taiwan", "台湾"),
    # 特殊地区
    ("overseas", "化外之地"),
]

REGION_DICT = dict(REGION_CHOICES)


# ============ PVP 系统常量 ============


class PVPConstants:
    """PVP系统常量"""

    # 坐标范围
    COORDINATE_MIN = 1
    COORDINATE_MAX = 999

    # 保护时间
    NEWBIE_PROTECTION_DAYS = 7  # 新手保护7天
    RELOCATION_COOLDOWN_DAYS = 30  # 迁移冷却30天

    # 侦察系统
    SCOUT_BASE_SUCCESS_RATE = 0.5  # 基础成功率50%
    SCOUT_TECH_RATE_PER_LEVEL = 0.05  # 每级侦察术增加5%
    SCOUT_TRAVEL_TIME_PER_DISTANCE = 2  # 每单位距离2秒
    SCOUT_BASE_TRAVEL_TIME = 60  # 基础侦察时间60秒
    SCOUT_COOLDOWN_MINUTES = 30  # 同一目标冷却30分钟
    SCOUT_TROOP_KEY = "scout"  # 探子兵种key
    SCOUT_MIN_SUCCESS_RATE = 0.10  # 最低成功率10%
    SCOUT_MAX_SUCCESS_RATE = 0.95  # 最高成功率95%

    # 踢馆系统
    RAID_PRESTIGE_RANGE = 500  # 声望差±500以内可攻击
    RAID_MAX_CONCURRENT = 3  # 同时最多3次出征
    RAID_BASE_TRAVEL_TIME = 300  # 基础行军时间300秒（5分钟）
    RAID_TRAVEL_TIME_PER_DISTANCE = 3  # 每单位距离3秒
    RAID_CROSS_REGION_MULTIPLIER = 1.5  # 跨区系数
    RAID_MAX_DAILY_ATTACKS_RECEIVED = 8  # 每个庄园每24小时最多被攻击次数（防小号集群）

    # 俘获/监牢
    RAID_CAPTURE_GUEST_RATE = 0.5  # 单场胜利后俘获失败方出战门客的概率（单场最多1名）【临时测试：50%】
    JAIL_LOYALTY_DAILY_DECAY = 5  # 被俘期间每日忠诚度衰减值
    JAIL_RECRUIT_LOYALTY_THRESHOLD = 30  # 忠诚度<=该值可招募
    JAIL_RECRUIT_GOLD_BAR_COST = 1  # 招募俘虏消耗金条数量（gold_bar）
    JAIL_PERSUADE_GOLD_BAR_COST = 1  # 劝降消耗金条数量
    JAIL_PERSUADE_LOYALTY_MIN = 5  # 劝降最小忠诚度减少
    JAIL_PERSUADE_LOYALTY_MAX = 10  # 劝降最大忠诚度减少

    # 战利品
    LOOT_RESOURCE_MIN_PERCENT = 0.10  # 最低掠夺10%
    LOOT_RESOURCE_MAX_PERCENT = 0.30  # 最高掠夺30%
    LOOT_ITEM_BASE_CHANCE = 0.20  # 物品掠夺基础概率20%
    LOOT_ITEM_MAX_COUNT = 3  # 每次最多掠夺3件物品
    LOOT_ITEM_MAX_QUANTITY_PERCENT = 0.20  # 每件物品最多掠夺20%
    LOOT_ITEM_MAX_QUANTITY = 5  # 每件物品最多掠夺5个

    # 装备回收
    EQUIPMENT_RECOVERY_CHANCE = 0.20  # 装备回收概率20%

    # 声望变化
    RAID_ATTACKER_WIN_PRESTIGE = 50  # 进攻胜利+50
    RAID_ATTACKER_LOSE_PRESTIGE = -30  # 进攻失败-30
    RAID_DEFENDER_WIN_PRESTIGE = 30  # 防守胜利+30
    RAID_DEFENDER_LOSE_PRESTIGE = -20  # 防守失败-20

    # 资产等级划分（用于侦察报告和迁移费用）
    ASSET_LEVEL_POOR = 10000  # 匮乏 < 10,000
    ASSET_LEVEL_NORMAL = 50000  # 一般 10,000 ~ 50,000
    ASSET_LEVEL_RICH = 200000  # 充裕 50,000 ~ 200,000
    # 富足 > 200,000

    # 迁移费用（金条）
    RELOCATION_COST_POOR = 1  # 匮乏
    RELOCATION_COST_NORMAL = 3  # 一般
    RELOCATION_COST_RICH = 6  # 充裕
    RELOCATION_COST_WEALTHY = 10  # 富足

    # 物品稀有度掠夺系数
    RARITY_LOOT_MULTIPLIER = {
        "black": 1.0,
        "gray": 0.8,
        "green": 0.5,
        "red": 0.35,
        "blue": 0.2,
        "purple": 0.1,
        "orange": 0.05,
    }

    # 经验果稀有度系数
    RARITY_EXP_MULTIPLIER = {
        "black": 0.5,
        "gray": 0.8,
        "green": 1.0,
        "red": 1.5,
        "blue": 2.0,
        "purple": 3.0,
        "orange": 5.0,
    }


# ============ UI/分页常量 ============


class UIConstants:
    """UI显示相关常量"""

    # 分页设置
    MESSAGES_PER_PAGE = 5  # 消息列表每页显示数量
    FORGE_ITEMS_PER_PAGE = 6  # 锻造页面每页显示数量
    MAP_SEARCH_PAGE_SIZE = 5  # 地图搜索每页数量
    MAP_SEARCH_NAME_LIMIT = 50  # 按名称搜索最大结果数
    RANKING_DEFAULT_LIMIT = 50  # 排行榜默认显示数量
    HISTORY_DEFAULT_LIMIT = 20  # 历史记录默认显示数量

    # 列表显示限制
    RECRUIT_RECORDS_DISPLAY = 6  # 招募记录显示数量
    ACTIVE_RUNS_DISPLAY = 5  # 进行中任务显示数量


# ============ 庄园名称验证常量 ============


class ManorNameConstants:
    """庄园名称验证相关常量"""

    MIN_LENGTH = 2  # 最小长度
    MAX_LENGTH = 12  # 最大长度

    # 敏感词列表（可扩展，支持中英文）
    BANNED_WORDS = frozenset(
        [
            "admin",
            "gm",
            "管理员",
            "客服",
            "官方",
            "system",
            "系统",
            "test",
            "测试",
        ]
    )

    # 任务扫描批量大小
    SCAN_BATCH_SIZE = 200  # Celery任务扫描批量大小

    # 坐标生成最大尝试次数
    COORDINATE_MAX_ATTEMPTS = 100
