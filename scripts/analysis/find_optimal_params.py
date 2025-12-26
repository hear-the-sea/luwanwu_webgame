#!/usr/bin/env python3
"""
反向计算：从目标反推参数
目标：最后一级2000万银两，总时长6个月
"""
import math

def calculate_total(base_cost, cost_growth, base_time, time_growth, max_level):
    """计算总成本和总时间"""
    total_cost = 0
    total_time = 0
    last_cost = 0

    for level in range(1, max_level + 1):
        cost_multiplier = cost_growth ** (level - 1)
        time_multiplier = time_growth ** (level - 1)

        cost = math.ceil(base_cost * cost_multiplier)
        duration = math.ceil(base_time * time_multiplier)

        total_cost += cost
        total_time += duration

        if level == max_level:
            last_cost = cost

    return {
        'total_cost': total_cost,
        'total_time_days': total_time / 86400,
        'last_level_cost': last_cost,
    }

def find_best_params(base_costs, cost_growths, base_times, time_growths, max_level, target_last_cost, target_days):
    """遍历参数组合，找到最接近目标的方案"""
    best_scenarios = []

    for base_cost in base_costs:
        for cost_growth in cost_growths:
            for base_time in base_times:
                for time_growth in time_growths:
                    result = calculate_total(base_cost, cost_growth, base_time, time_growth, max_level)

                    # 计算偏差
                    cost_diff = abs(result['last_level_cost'] - target_last_cost) / target_last_cost
                    time_diff = abs(result['total_time_days'] - target_days) / target_days

                    # 筛选：最后一级成本在目标±20%，总时长在目标±30%
                    if cost_diff <= 0.2 and time_diff <= 0.3:
                        best_scenarios.append({
                            'base_cost': base_cost,
                            'cost_growth': cost_growth,
                            'base_time': base_time,
                            'time_growth': time_growth,
                            'result': result,
                            'cost_diff': cost_diff,
                            'time_diff': time_diff,
                            'score': cost_diff + time_diff,  # 综合得分，越小越好
                        })

    # 按综合得分排序
    best_scenarios.sort(key=lambda x: x['score'])
    return best_scenarios[:5]  # 返回前5个最佳方案

# 目标
TARGET_LAST_COST = 20_000_000
TARGET_DAYS = 180

print("=" * 80)
print("反向计算最佳参数组合")
print("=" * 80)
print(f"目标：最后一级成本 = {TARGET_LAST_COST:,} 银两 (±20%)")
print(f"目标：总时长 = {TARGET_DAYS} 天 (±30%)")
print()

# ========== 聚贤庄 (Lv20) ==========
print("【聚贤庄 (Lv20)】参数搜索")
print("-" * 80)

juxian_base_costs = [300, 500, 800, 1000, 1500, 2000]
juxian_cost_growths = [1.62, 1.64, 1.66, 1.68, 1.70]
juxian_base_times = [1800, 3600, 7200, 10800, 14400]
juxian_time_growths = [1.38, 1.40, 1.42, 1.44, 1.46]

juxian_best = find_best_params(
    juxian_base_costs,
    juxian_cost_growths,
    juxian_base_times,
    juxian_time_growths,
    20,
    TARGET_LAST_COST,
    TARGET_DAYS
)

if juxian_best:
    print(f"\n找到 {len(juxian_best)} 个符合条件的方案:\n")
    for i, scenario in enumerate(juxian_best, 1):
        print(f"方案{i}:")
        print("  参数配置:")
        print(f"    base_cost: {scenario['base_cost']:,}")
        print(f"    cost_growth: {scenario['cost_growth']}")
        print(f"    base_time: {scenario['base_time']}s ({scenario['base_time']/3600:.1f}小时)")
        print(f"    time_growth: {scenario['time_growth']}")
        print()
        print("  预期效果:")
        print(f"    总成本: {scenario['result']['total_cost']:,} 银两")
        print(f"    总时长: {scenario['result']['total_time_days']:.1f} 天")
        print(f"    最后一级: {scenario['result']['last_level_cost']:,} 银两")
        print()
        print("  偏差评估:")
        print(f"    成本偏差: {scenario['cost_diff']*100:+.1f}%")
        print(f"    时长偏差: {scenario['time_diff']*100:+.1f}%")
        print(f"    综合得分: {scenario['score']:.3f} (越小越好)")
        print()
        print("-" * 80)
else:
    print("⚠️ 未找到符合条件的方案，需要扩大搜索范围")

# ========== 悠嘻宝塔 (Lv6) ==========
print("\n\n【悠嘻宝塔 (Lv6)】参数搜索")
print("-" * 80)

youxi_base_costs = [30000, 50000, 80000, 100000, 150000]
youxi_cost_growths = [2.8, 2.9, 3.0, 3.1, 3.2, 3.3]
youxi_base_times = [14400, 28800, 43200, 86400, 129600]
youxi_time_growths = [2.0, 2.1, 2.2, 2.3, 2.4]

youxi_best = find_best_params(
    youxi_base_costs,
    youxi_cost_growths,
    youxi_base_times,
    youxi_time_growths,
    6,
    TARGET_LAST_COST,
    TARGET_DAYS
)

if youxi_best:
    print(f"\n找到 {len(youxi_best)} 个符合条件的方案:\n")
    for i, scenario in enumerate(youxi_best, 1):
        print(f"方案{i}:")
        print("  参数配置:")
        print(f"    base_cost: {scenario['base_cost']:,}")
        print(f"    cost_growth: {scenario['cost_growth']}")
        print(f"    base_time: {scenario['base_time']}s ({scenario['base_time']/3600:.1f}小时 / {scenario['base_time']/86400:.1f}天)")
        print(f"    time_growth: {scenario['time_growth']}")
        print()
        print("  预期效果:")
        print(f"    总成本: {scenario['result']['total_cost']:,} 银两")
        print(f"    总时长: {scenario['result']['total_time_days']:.1f} 天")
        print(f"    最后一级: {scenario['result']['last_level_cost']:,} 银两")
        print(f"    粮食成本: {int(scenario['result']['total_cost']*0.2):,} (按20%估算)")
        print()
        print("  偏差评估:")
        print(f"    成本偏差: {scenario['cost_diff']*100:+.1f}%")
        print(f"    时长偏差: {scenario['time_diff']*100:+.1f}%")
        print(f"    综合得分: {scenario['score']:.3f} (越小越好)")
        print()
        print("-" * 80)
else:
    print("⚠️ 未找到符合条件的方案，需要扩大搜索范围")

print()
print("=" * 80)
print("💡 使用建议")
print("=" * 80)
print()
print("1. 选择综合得分最低的方案（偏差最小）")
print("2. 考虑前期体验，可以适当降低base_cost，提高cost_growth")
print("3. 根据实际测试反馈微调参数")
print()
