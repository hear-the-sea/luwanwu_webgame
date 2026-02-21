#!/usr/bin/env python3
"""
探索聚贤庄和悠嘻宝塔达到6个月升级时间的参数组合
"""
import math


def calculate_total_time(base_time, time_growth, max_level):
    """计算总升级时间（秒）"""
    total = 0
    for level in range(1, max_level + 1):
        multiplier = time_growth ** (level - 1)
        duration = math.ceil(base_time * multiplier)
        total += duration
    return total


def calculate_total_cost(base_cost, cost_growth, max_level):
    """计算总升级成本"""
    total = 0
    for level in range(1, max_level + 1):
        multiplier = cost_growth ** (level - 1)
        cost = math.ceil(base_cost * multiplier)
        total += cost
    return total


# 目标：6个月 = 180天 = 180 * 86400秒 = 15,552,000秒
TARGET_DAYS = 180
TARGET_SECONDS = TARGET_DAYS * 86400

print("=" * 80)
print("探索「6个月升满级」的参数组合")
print("=" * 80)
print(f"目标时长: {TARGET_DAYS}天 ({TARGET_SECONDS:,}秒)")
print()

# ========== 聚贤庄 (Lv20) ==========
print("【聚贤庄 (Lv20)】参数探索")
print("-" * 80)

juxian_scenarios = [
    {
        "name": "方案1：低增长型",
        "base_time": 3600,  # 1小时
        "time_growth": 1.35,
        "base_cost": 5000,
        "cost_growth": 1.42,
        "max_level": 20,
    },
    {
        "name": "方案2：中等增长",
        "base_time": 7200,  # 2小时
        "time_growth": 1.32,
        "base_cost": 8000,
        "cost_growth": 1.40,
        "max_level": 20,
    },
    {
        "name": "方案3：平衡型",
        "base_time": 10800,  # 3小时
        "time_growth": 1.30,
        "base_cost": 10000,
        "cost_growth": 1.38,
        "max_level": 20,
    },
    {
        "name": "方案4：高基础极低增长",
        "base_time": 21600,  # 6小时
        "time_growth": 1.28,
        "base_cost": 15000,
        "cost_growth": 1.35,
        "max_level": 20,
    },
    {
        "name": "方案5：超高基础微增长",
        "base_time": 43200,  # 12小时
        "time_growth": 1.25,
        "base_cost": 20000,
        "cost_growth": 1.32,
        "max_level": 20,
    },
]

for scenario in juxian_scenarios:
    total_time = calculate_total_time(scenario["base_time"], scenario["time_growth"], scenario["max_level"])
    total_cost = calculate_total_cost(scenario["base_cost"], scenario["cost_growth"], scenario["max_level"])
    days = total_time / 86400

    print(f"\n{scenario['name']}")
    print(
        f"  参数: base_time={scenario['base_time']}s ({scenario['base_time']/3600:.1f}h), "
        f"time_growth={scenario['time_growth']}, "
        f"base_cost={scenario['base_cost']}, "
        f"cost_growth={scenario['cost_growth']}"
    )
    print(f"  总时长: {days:.1f}天 ({total_time/3600:.1f}小时)")
    print(f"  总成本: {total_cost:,}银两")

    if days >= TARGET_DAYS * 0.9 and days <= TARGET_DAYS * 1.2:
        print(f"  ✅ 符合目标（{TARGET_DAYS}天±20%）")
    elif days < TARGET_DAYS * 0.9:
        print(f"  ⚠️ 偏短（目标{TARGET_DAYS}天，差{TARGET_DAYS - days:.1f}天）")
    else:
        print(f"  ⚠️ 偏长（目标{TARGET_DAYS}天，超{days - TARGET_DAYS:.1f}天）")

# ========== 悠嘻宝塔 (Lv6) ==========
print("\n\n【悠嘻宝塔 (Lv6)】参数探索")
print("-" * 80)

youxi_scenarios = [
    {
        "name": "方案1：极高指数增长",
        "base_time": 86400,  # 1天
        "time_growth": 2.0,
        "base_cost": 50000,
        "cost_growth": 2.0,
        "max_level": 6,
    },
    {
        "name": "方案2：超高基础时间",
        "base_time": 172800,  # 2天
        "time_growth": 1.9,
        "base_cost": 80000,
        "cost_growth": 1.9,
        "max_level": 6,
    },
    {
        "name": "方案3：平衡型",
        "base_time": 259200,  # 3天
        "time_growth": 1.8,
        "base_cost": 100000,
        "cost_growth": 1.8,
        "max_level": 6,
    },
    {
        "name": "方案4：低增长高基础",
        "base_time": 432000,  # 5天
        "time_growth": 1.7,
        "base_cost": 150000,
        "cost_growth": 1.7,
        "max_level": 6,
    },
]

for scenario in youxi_scenarios:
    total_time = calculate_total_time(scenario["base_time"], scenario["time_growth"], scenario["max_level"])
    # 悠嘻宝塔需要粮食和银两
    total_silver = calculate_total_cost(scenario["base_cost"], scenario["cost_growth"], scenario["max_level"])
    # 假设粮食成本是银两的20%
    total_grain = int(total_silver * 0.2)

    days = total_time / 86400

    print(f"\n{scenario['name']}")
    print(
        f"  参数: base_time={scenario['base_time']}s ({scenario['base_time']/86400:.1f}天), "
        f"time_growth={scenario['time_growth']}"
    )
    print(
        f"        base_cost={{silver: {scenario['base_cost']}, grain: {int(scenario['base_cost']*0.2)}}}, "
        f"cost_growth={scenario['cost_growth']}"
    )
    print(f"  总时长: {days:.1f}天 ({total_time/3600:.1f}小时)")
    print(f"  总成本: {total_silver:,}银两 + {total_grain:,}粮食")

    if days >= TARGET_DAYS * 0.9 and days <= TARGET_DAYS * 1.2:
        print(f"  ✅ 符合目标（{TARGET_DAYS}天±20%）")
    elif days < TARGET_DAYS * 0.9:
        print(f"  ⚠️ 偏短（目标{TARGET_DAYS}天，差{TARGET_DAYS - days:.1f}天）")
    else:
        print(f"  ⚠️ 偏长（目标{TARGET_DAYS}天，超{days - TARGET_DAYS:.1f}天）")

print("\n" + "=" * 80)
print("💡 推荐方案")
print("=" * 80)
print()
print("考虑因素：")
print("  1. 时间接近180天目标")
print("  2. 成本合理，不会过度膨胀")
print("  3. 增长曲线平滑，避免后期单级时间过长")
print("  4. 与其他建筑形成合理的进度梯度")
print()
print("建议选择「平衡型」方案，既达到长期目标，又保持合理的游戏节奏")
print()
