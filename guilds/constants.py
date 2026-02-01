"""
帮会系统常量定义

集中管理帮会模块的所有配置常量。
"""

import re

# ============ 分页与列表 ============

# 帮会列表每页显示数量
GUILD_LIST_PAGE_SIZE = 20

# 帮会大厅首页推荐数量
GUILD_HALL_DISPLAY_LIMIT = 20


# ============ 帮会创建与升级 ============

# 创建帮会成本
GUILD_CREATION_COST = {'gold_bar': 2}

# 帮会升级基础成本（金条）
GUILD_UPGRADE_BASE_COST = 5


# ============ 帮会名称校验 ============

GUILD_NAME_MIN_LENGTH = 2
GUILD_NAME_MAX_LENGTH = 12

# 允许：中文、英文、数字、下划线
GUILD_NAME_PATTERN = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_]+$')


# ============ 捐赠系统 ============

# 贡献兑换比例
CONTRIBUTION_RATES = {
    'silver': 1,      # 1银两 = 1贡献
    'grain': 2,       # 1粮食 = 2贡献
}

# 每日捐赠上限
DAILY_DONATION_LIMITS = {
    'silver': 100000,  # 10万银两
    'grain': 50000,    # 5万粮食
}

# 最小捐赠数量
MIN_DONATION_AMOUNT = 100


# ============ 帮会科技 ============

# 科技升级成本配置
TECH_UPGRADE_COSTS = {
    # 生产类科技（成本较低）
    'equipment_forge': {'silver': 5000, 'grain': 2000, 'gold_bar': 1},
    'experience_refine': {'silver': 5000, 'grain': 2000, 'gold_bar': 1},
    'resource_supply': {'silver': 4000, 'grain': 3000, 'gold_bar': 1},

    # 战斗类科技（成本中等）
    'military_study': {'silver': 8000, 'grain': 3000, 'gold_bar': 2},
    'troop_tactics': {'silver': 8000, 'grain': 3000, 'gold_bar': 2},

    # 福利类科技（成本较高）
    'resource_boost': {'silver': 10000, 'grain': 5000, 'gold_bar': 3},
    'march_speed': {'silver': 10000, 'grain': 5000, 'gold_bar': 3},
}

# 科技名称映射
TECH_NAMES = {
    'equipment_forge': '装备锻造',
    'experience_refine': '经验炼制',
    'resource_supply': '资源补给',
    'military_study': '兵法研习',
    'troop_tactics': '强兵战术',
    'resource_boost': '资源增产',
    'march_speed': '行军加速',
}


# ============ 帮会仓库 ============

# 兑换成本配置
EXCHANGE_COSTS = {
    # 装备
    'gear_green': 50,
    'gear_blue': 150,
    'gear_purple': 500,
    'gear_orange': 2000,

    # 经验道具
    'exp_small': 30,
    'exp_medium': 100,
    'exp_large': 400,

    # 资源包
    'resource_pack_common': 20,
    'resource_pack_advanced': 80,
}

# 每日兑换上限
DAILY_EXCHANGE_LIMIT = 10
