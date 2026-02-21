#!/usr/bin/env python3
"""
检查家丁房升级参数和总成本
"""
import math

import yaml

with open("data/building_templates.yaml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

# 找到家丁房
jiading = None
for b in data["buildings"]:
    if b["key"] == "jiadingfang":
        jiading = b
        break

if not jiading:
    print("❌ 未找到家丁房配置")
    exit(1)

max_level = 30

print("═" * 70)
print(f"家丁房 ({jiading['name']}) 参数检查")
print("═" * 70)
print()
print("基础参数:")
print(f"  - 类型: {jiading['category']}")
print(f"  - 最大等级: {max_level}")
print(f"  - 基础升级时间: {jiading['base_upgrade_time']}秒 ({jiading['base_upgrade_time']/60:.1f}分钟)")
print(f"  - 时间增长系数: {jiading['time_growth']}")
print(f"  - 基础成本: {jiading['base_cost']}")
print(f"  - 成本增长系数: {jiading['cost_growth']}")
print()

# 计算总成本和总时间
total_silver = 0
total_grain = 0
total_time = 0

print("各级升级明细:")
print(f"{'等级':<6} {'升级成本':>20} {'升级时间':>15} {'累计成本':>25} {'累计时间':>12}")
print("-" * 90)

for level in range(1, max_level + 1):
    # 成本
    cost_multiplier = jiading["cost_growth"] ** (level - 1)
    for resource, amount in jiading["base_cost"].items():
        cost = math.ceil(amount * cost_multiplier)
        if resource == "silver":
            total_silver += cost
        elif resource == "grain":
            total_grain += cost

    # 时间
    time_multiplier = jiading["time_growth"] ** (level - 1)
    duration = math.ceil(jiading["base_upgrade_time"] * time_multiplier)
    total_time += duration

    # 只显示关键等级
    if level in [1, 2, 5, 10, 15, 20, 25, 30]:
        # 格式化成本
        silver = math.ceil(jiading["base_cost"]["silver"] * cost_multiplier)
        cost_str = f"{silver:,}银"

        # 格式化时间
        if duration < 3600:
            duration_str = f"{duration/60:.0f}分钟"
        elif duration < 86400:
            duration_str = f"{duration/3600:.1f}小时"
        else:
            duration_str = f"{duration/86400:.1f}天"

        # 格式化累计时间
        if total_time < 86400:
            total_time_str = f"{total_time/3600:.1f}小时"
        else:
            total_time_str = f"{total_time/86400:.1f}天"

        print(f"Lv{level:<4} {cost_str:>20} {duration_str:>15} {total_silver:>20,}银 {total_time_str:>12}")

print("-" * 90)
print()
print("📊 总计（1→Lv30）:")
print(f"  - 总银两: {total_silver:,}")
print(f"  - 总粮食: {total_grain:,}")
print(f"  - 总时长: {total_time/86400:.1f}天 ({total_time/3600:.0f}小时)")
print(
    f"  - 最后一级成本: {math.ceil(jiading['base_cost']['silver'] * (jiading['cost_growth'] ** (max_level - 1))):,}银"
)
print()

# 评估
print("⚖️ 平衡性评估:")
print(
    f"  - 前期体验: Lv1升级仅需{jiading['base_cost']['silver']}银两 + {jiading['base_upgrade_time']/60:.0f}分钟 (非常友好)"
)
last_cost = math.ceil(jiading["base_cost"]["silver"] * (jiading["cost_growth"] ** (max_level - 1)))
print(f"  - 后期挑战: Lv30升级需要{last_cost:,}银两 (适中)")
print(f"  - 总时长: {total_time/86400:.1f}天 (合理)")
print()
