#!/usr/bin/env python3
"""
探索「前期友好，后期硬核」的参数组合
目标：
1. 前期不要太难（base_cost降低）
2. 后期指数增长（cost_growth提高）
3. 最后一级达到2000万银两
4. 总时长保持在6个月左右
"""
import math

def calculate_upgrade_details(base_cost, cost_growth, base_time, time_growth, max_level):
    """计算每一级的详细数据"""
    levels = []
    total_cost = 0
    total_time = 0

    for level in range(1, max_level + 1):
        cost_multiplier = cost_growth ** (level - 1)
        time_multiplier = time_growth ** (level - 1)

        cost = math.ceil(base_cost * cost_multiplier)
        duration = math.ceil(base_time * time_multiplier)

        total_cost += cost
        total_time += duration

        levels.append({
            'level': level,
            'cost': cost,
            'duration': duration,
            'duration_hours': duration / 3600,
            'duration_days': duration / 86400,
        })

    return {
        'levels': levels,
        'total_cost': total_cost,
        'total_time': total_time,
        'total_days': total_time / 86400,
        'last_level_cost': levels[-1]['cost'],
    }

# 目标：最后一级2000万银两
TARGET_LAST_LEVEL_COST = 20_000_000
TARGET_DAYS = 180

print("=" * 80)
print("探索「前期友好，后期硬核」参数组合")
print("=" * 80)
print(f"目标：最后一级成本 = {TARGET_LAST_LEVEL_COST:,} 银两")
print(f"目标：总时长 ≈ {TARGET_DAYS} 天")
print()

# ========== 聚贤庄 (Lv20) ==========
print("【聚贤庄 (Lv20)】参数探索")
print("-" * 80)
print()

# 计算需要的growth：如果最后一级是2000万
# last_cost = base_cost * growth^(max_level - 1)
# 2000万 = base_cost * growth^19

juxian_scenarios = [
    {
        'name': '方案1：极低基础极高增长',
        'base_cost': 500,
        'cost_growth': 1.65,  # 500 * 1.65^19 ≈ 38M (太高)
        'base_time': 1800,  # 30分钟
        'time_growth': 1.40,
        'max_level': 20,
    },
    {
        'name': '方案2：低基础高增长',
        'base_cost': 1000,
        'cost_growth': 1.60,  # 1000 * 1.60^19 ≈ 20M ✓
        'base_time': 3600,  # 1小时
        'time_growth': 1.38,
        'max_level': 20,
    },
    {
        'name': '方案3：适中基础中等增长',
        'base_cost': 2000,
        'cost_growth': 1.55,  # 2000 * 1.55^19 ≈ 13.4M
        'base_time': 7200,  # 2小时
        'time_growth': 1.35,
        'max_level': 20,
    },
    {
        'name': '方案4：较高基础较低增长',
        'base_cost': 5000,
        'cost_growth': 1.48,  # 5000 * 1.48^19 ≈ 11.9M
        'base_time': 14400,  # 4小时
        'time_growth': 1.32,
        'max_level': 20,
    },
]

for scenario in juxian_scenarios:
    result = calculate_upgrade_details(
        scenario['base_cost'],
        scenario['cost_growth'],
        scenario['base_time'],
        scenario['time_growth'],
        scenario['max_level']
    )

    print(f"{scenario['name']}")
    print(f"  参数: base_cost={scenario['base_cost']:,}, cost_growth={scenario['cost_growth']}")
    print(f"        base_time={scenario['base_time']}s ({scenario['base_time']/3600:.1f}h), time_growth={scenario['time_growth']}")
    print()

    # 显示前3级和后3级的详细数据
    print("  前3级明细:")
    for level_data in result['levels'][:3]:
        print(f"    Lv{level_data['level']:2d} → {level_data['cost']:>12,} 银两  {level_data['duration_hours']:>6.1f}小时")

    print("  ...")

    print("  后3级明细:")
    for level_data in result['levels'][-3:]:
        print(f"    Lv{level_data['level']:2d} → {level_data['cost']:>12,} 银两  {level_data['duration_days']:>6.1f}天")

    print()
    print("  📊 总计:")
    print(f"     总成本: {result['total_cost']:,} 银两")
    print(f"     总时长: {result['total_days']:.1f} 天")
    print(f"     最后一级成本: {result['last_level_cost']:,} 银两")

    # 评估
    cost_diff_percent = (result['last_level_cost'] - TARGET_LAST_LEVEL_COST) / TARGET_LAST_LEVEL_COST * 100
    time_diff_percent = (result['total_days'] - TARGET_DAYS) / TARGET_DAYS * 100

    if abs(cost_diff_percent) <= 20 and abs(time_diff_percent) <= 20:
        print("     ✅ 符合目标（成本±20%，时间±20%）")
    else:
        if cost_diff_percent > 20:
            print(f"     ⚠️ 最后一级成本偏高（{cost_diff_percent:+.0f}%）")
        elif cost_diff_percent < -20:
            print(f"     ⚠️ 最后一级成本偏低（{cost_diff_percent:+.0f}%）")

        if time_diff_percent > 20:
            print(f"     ⚠️ 总时长偏长（{time_diff_percent:+.0f}%）")
        elif time_diff_percent < -20:
            print(f"     ⚠️ 总时长偏短（{time_diff_percent:+.0f}%）")

    print()
    print("-" * 80)
    print()

# ========== 悠嘻宝塔 (Lv6) ==========
print()
print("【悠嘻宝塔 (Lv6)】参数探索")
print("-" * 80)
print()

# 最后一级2000万：2000万 = base_cost * growth^5

youxi_scenarios = [
    {
        'name': '方案1：极低基础极高增长',
        'base_cost': 50000,
        'cost_growth': 3.0,  # 50000 * 3.0^5 = 12.15M (偏低)
        'base_time': 14400,  # 4小时
        'time_growth': 2.2,
        'max_level': 6,
    },
    {
        'name': '方案2：低基础高增长',
        'base_cost': 80000,
        'cost_growth': 2.8,  # 80000 * 2.8^5 ≈ 14M (接近)
        'base_time': 28800,  # 8小时
        'time_growth': 2.1,
        'max_level': 6,
    },
    {
        'name': '方案3：适中基础中高增长',
        'base_cost': 100000,
        'cost_growth': 2.68,  # 100000 * 2.68^5 ≈ 13M
        'base_time': 43200,  # 12小时
        'time_growth': 2.0,
        'max_level': 6,
    },
    {
        'name': '方案4：较高基础较低增长',
        'base_cost': 150000,
        'cost_growth': 2.5,  # 150000 * 2.5^5 ≈ 14.6M
        'base_time': 86400,  # 1天
        'time_growth': 1.9,
        'max_level': 6,
    },
]

for scenario in youxi_scenarios:
    result = calculate_upgrade_details(
        scenario['base_cost'],
        scenario['cost_growth'],
        scenario['base_time'],
        scenario['time_growth'],
        scenario['max_level']
    )

    print(f"{scenario['name']}")
    print(f"  参数: base_cost={scenario['base_cost']:,}, cost_growth={scenario['cost_growth']}")
    print(f"        base_time={scenario['base_time']}s ({scenario['base_time']/3600:.1f}h), time_growth={scenario['time_growth']}")
    print()

    # 显示每一级的详细数据
    print("  各级明细:")
    for level_data in result['levels']:
        if level_data['duration_days'] >= 1:
            duration_str = f"{level_data['duration_days']:>6.1f}天"
        else:
            duration_str = f"{level_data['duration_hours']:>6.1f}小时"
        print(f"    Lv{level_data['level']} → {level_data['cost']:>12,} 银两  {duration_str}")

    print()
    print("  📊 总计:")
    print(f"     总成本: {result['total_cost']:,} 银两")
    print(f"     总时长: {result['total_days']:.1f} 天")
    print(f"     最后一级成本: {result['last_level_cost']:,} 银两")

    # 悠嘻宝塔也需要粮食（假设是银两的20%）
    grain_cost = int(result['total_cost'] * 0.2)
    print(f"     粮食成本: {grain_cost:,} (按银两20%估算)")

    # 评估
    cost_diff_percent = (result['last_level_cost'] - TARGET_LAST_LEVEL_COST) / TARGET_LAST_LEVEL_COST * 100
    time_diff_percent = (result['total_days'] - TARGET_DAYS) / TARGET_DAYS * 100

    if abs(cost_diff_percent) <= 30 and abs(time_diff_percent) <= 20:
        print("     ✅ 符合目标（成本±30%，时间±20%）")
    else:
        if cost_diff_percent > 30:
            print(f"     ⚠️ 最后一级成本偏高（{cost_diff_percent:+.0f}%）")
        elif cost_diff_percent < -30:
            print(f"     ⚠️ 最后一级成本偏低（{cost_diff_percent:+.0f}%）")

        if time_diff_percent > 20:
            print(f"     ⚠️ 总时长偏长（{time_diff_percent:+.0f}%）")
        elif time_diff_percent < -20:
            print(f"     ⚠️ 总时长偏短（{time_diff_percent:+.0f}%）")

    print()
    print("-" * 80)
    print()

print()
print("=" * 80)
print("💡 推荐原则")
print("=" * 80)
print()
print("1. 前期友好：")
print("   - 聚贤庄 Lv1：500-2000银两，1-4小时")
print("   - 悠嘻宝塔 Lv1：5-15万银两，4-24小时")
print()
print("2. 后期硬核：")
print("   - 聚贤庄 Lv20：1500-2500万银两，20-40天")
print("   - 悠嘻宝塔 Lv6：1000-2000万银两，30-60天")
print()
print("3. 曲线设计：")
print("   - 低base_cost + 高cost_growth = 前期容易，后期陡峭")
print("   - 同时调整time_growth，保持总时长在6个月左右")
print()
