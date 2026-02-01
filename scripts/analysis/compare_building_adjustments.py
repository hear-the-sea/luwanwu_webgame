#!/usr/bin/env python3
"""
建筑参数调整方案对比
"""
import math


def calculate_building_total(base_cost, cost_growth, base_time, time_growth, max_level):
    """计算建筑1→满级的总成本和总时间"""
    total_silver = 0
    total_grain = 0
    total_time = 0

    for level in range(1, max_level + 1):
        # 成本
        cost_multiplier = cost_growth ** (level - 1)
        silver = base_cost.get('silver', 0)
        grain = base_cost.get('grain', 0)
        total_silver += math.ceil(silver * cost_multiplier)
        total_grain += math.ceil(grain * cost_multiplier)

        # 时间
        time_multiplier = time_growth ** (level - 1)
        duration = math.ceil(base_time * time_multiplier)
        total_time += duration

    return {
        'silver': total_silver,
        'grain': total_grain,
        'time_seconds': total_time,
        'time_minutes': total_time / 60,
        'time_hours': total_time / 3600,
        'time_days': total_time / 86400,
    }


print("=" * 80)
print("建筑参数调整方案对比")
print("=" * 80)
print()

# ========== 藏宝阁 ==========
print("【藏宝阁】缩短时间")
print("-" * 80)

current = {
    'name': '当前配置',
    'max_level': 30,
    'base_cost': {'silver': 7500},
    'cost_growth': 1.4,
    'base_time': 600,
    'time_growth': 1.3,
}

plan1 = {
    'name': '方案1：降低max_level',
    'max_level': 20,
    'base_cost': {'silver': 7500},
    'cost_growth': 1.4,
    'base_time': 600,
    'time_growth': 1.3,
}

plan2 = {
    'name': '方案2：降低time_growth',
    'max_level': 30,
    'base_cost': {'silver': 7500},
    'cost_growth': 1.4,
    'base_time': 600,
    'time_growth': 1.2,
}

plan3 = {
    'name': '方案3：降低max_level+调整增长',
    'max_level': 20,
    'base_cost': {'silver': 7500},
    'cost_growth': 1.35,
    'base_time': 600,
    'time_growth': 1.25,
}

for plan in [current, plan1, plan2, plan3]:
    result = calculate_building_total(
        plan['base_cost'],
        plan['cost_growth'],
        plan['base_time'],
        plan['time_growth'],
        plan['max_level']
    )
    print(f"\n{plan['name']} (Lv{plan['max_level']})")
    print(f"  - 参数: base_time={plan['base_time']}, time_growth={plan['time_growth']}, cost_growth={plan['cost_growth']}")
    print(f"  - 总时长: {result['time_days']:.2f}天 ({result['time_hours']:.1f}小时)")
    print(f"  - 总成本: {result['silver']:,}银两")

# ========== 聚贤庄 ==========
print()
print()
print("【聚贤庄】增加时间和资源消耗")
print("-" * 80)

current = {
    'name': '当前配置',
    'max_level': 20,
    'base_cost': {'silver': 470},
    'cost_growth': 1.35,
    'base_time': 240,
    'time_growth': 1.25,
}

plan1 = {
    'name': '方案1：中等提升',
    'max_level': 20,
    'base_cost': {'silver': 1500},
    'cost_growth': 1.38,
    'base_time': 480,
    'time_growth': 1.28,
}

plan2 = {
    'name': '方案2：大幅提升',
    'max_level': 20,
    'base_cost': {'silver': 2500},
    'cost_growth': 1.4,
    'base_time': 600,
    'time_growth': 1.3,
}

for plan in [current, plan1, plan2]:
    result = calculate_building_total(
        plan['base_cost'],
        plan['cost_growth'],
        plan['base_time'],
        plan['time_growth'],
        plan['max_level']
    )
    print(f"\n{plan['name']} (Lv{plan['max_level']})")
    print(f"  - 参数: base_cost={plan['base_cost']['silver']}, cost_growth={plan['cost_growth']}, base_time={plan['base_time']}, time_growth={plan['time_growth']}")
    print(f"  - 总时长: {result['time_days']:.2f}天 ({result['time_hours']:.1f}小时)")
    print(f"  - 总成本: {result['silver']:,}银两")

# ========== 悠嘻宝塔 ==========
print()
print()
print("【悠嘻宝塔】增加时间和资源消耗")
print("-" * 80)

current = {
    'name': '当前配置',
    'max_level': 6,
    'base_cost': {'grain': 300, 'silver': 1300},
    'cost_growth': 1.3,
    'base_time': 60,
    'time_growth': 1.2,
}

plan1 = {
    'name': '方案1：文档建议A2-1（中等）',
    'max_level': 6,
    'base_cost': {'grain': 1000, 'silver': 5000},
    'cost_growth': 1.55,
    'base_time': 600,
    'time_growth': 1.35,
}

plan2 = {
    'name': '方案2：文档建议A2-2（较重）',
    'max_level': 6,
    'base_cost': {'grain': 2000, 'silver': 8000},
    'cost_growth': 1.6,
    'base_time': 900,
    'time_growth': 1.4,
}

plan3 = {
    'name': '方案3：适中方案',
    'max_level': 6,
    'base_cost': {'grain': 1500, 'silver': 6000},
    'cost_growth': 1.5,
    'base_time': 720,
    'time_growth': 1.35,
}

for plan in [current, plan1, plan2, plan3]:
    result = calculate_building_total(
        plan['base_cost'],
        plan['cost_growth'],
        plan['base_time'],
        plan['time_growth'],
        plan['max_level']
    )
    print(f"\n{plan['name']} (Lv{plan['max_level']})")
    print(f"  - 参数: base_cost={{grain: {plan['base_cost']['grain']}, silver: {plan['base_cost']['silver']}}}")
    print(f"         cost_growth={plan['cost_growth']}, base_time={plan['base_time']}, time_growth={plan['time_growth']}")
    print(f"  - 总时长: {result['time_days']:.2f}天 ({result['time_hours']:.2f}小时)")
    print(f"  - 总成本: {result['silver']:,}银两 + {result['grain']:,}粮食")

print()
print("=" * 80)
print("推荐方案（平衡考虑）")
print("=" * 80)
print()
print("藏宝阁: 方案1（降低max_level到20）")
print("  理由：最简单直接，20级仓库容量已足够，且避免过度消耗")
print()
print("聚贤庄: 方案1（中等提升）")
print("  理由：门客容量是核心但非战斗功能，提升适度即可")
print()
print("悠嘻宝塔: 方案1（文档A2-1）")
print("  理由：出战上限是最核心战斗功能，应成为阶段性目标")
print()
