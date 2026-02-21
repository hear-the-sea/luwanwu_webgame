#!/usr/bin/env python3
import math

import yaml

with open("data/building_templates.yaml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

buildings = data["buildings"]

# 最大等级配置
max_levels = {
    "treasury": 20,  # 调整后
    "juxianzhuang": 20,
    "youxibaota": 6,
}

# 查看三个关键建筑
targets = ["treasury", "juxianzhuang", "youxibaota"]

for b in buildings:
    if b["key"] in targets:
        max_level = max_levels.get(b["key"], 20)

        print(f"═══ {b['name']} ({b['key']}) ═══")
        print(f"类型: {b['category']}")
        print(f"最大等级: {max_level}")
        print(f"基础升级时间: {b['base_upgrade_time']}秒 ({b['base_upgrade_time']/60:.1f}分钟)")
        print(f"时间增长系数: {b['time_growth']}")
        print(f"基础成本: {b['base_cost']}")
        print(f"成本增长系数: {b['cost_growth']}")

        # 计算1→满级的总成本和总时间
        total_silver = 0
        total_grain = 0
        total_time = 0

        for level in range(1, max_level + 1):
            # 成本
            cost_multiplier = b["cost_growth"] ** (level - 1)
            for resource, amount in b["base_cost"].items():
                cost = math.ceil(amount * cost_multiplier)
                if resource == "silver":
                    total_silver += cost
                elif resource == "grain":
                    total_grain += cost

            # 时间
            time_multiplier = b["time_growth"] ** (level - 1)
            duration = math.ceil(b["base_upgrade_time"] * time_multiplier)
            total_time += duration

        print(f"\n1→Lv{max_level} 总消耗:")
        print(f"  - 银两: {total_silver:,}")
        print(f"  - 粮食: {total_grain:,}")
        print(f"  - 时间: {total_time/60:.1f}分钟 ({total_time/3600:.2f}小时) ({total_time/86400:.2f}天)")
        print()
