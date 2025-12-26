#!/usr/bin/env python3
"""
验证家丁房容量计算
"""

# 新参数
RETAINER_CAPACITY_BASE = 50
RETAINER_CAPACITY_PER_LEVEL = 100

def calculate_capacity(level):
    """计算家丁房容量"""
    return RETAINER_CAPACITY_BASE + level * RETAINER_CAPACITY_PER_LEVEL

print("=" * 60)
print("家丁房容量验证")
print("=" * 60)
print()
print("参数配置:")
print(f"  基础容量: {RETAINER_CAPACITY_BASE}个位置（0级时）")
print(f"  每级增量: {RETAINER_CAPACITY_PER_LEVEL}个位置")
print("  满级: 30级")
print()

print("容量明细:")
print(f"{'等级':<6} {'容量':>12} {'累计增加':>12}")
print("-" * 40)

# 显示关键等级
key_levels = [0, 1, 2, 5, 10, 15, 20, 25, 30]

for level in key_levels:
    capacity = calculate_capacity(level)
    increase = capacity - RETAINER_CAPACITY_BASE
    print(f"Lv{level:<4} {capacity:>12,}    +{increase:>10,}")

print("-" * 40)
print()
print("✅ 验证结果:")
print(f"  - 0级（初始）: {calculate_capacity(0)}个位置 ✓")
print(f"  - 1级（首次升级）: {calculate_capacity(1)}个位置 ✓")
print(f"  - 30级（满级）: {calculate_capacity(30):,}个位置 ✓")
print()
print(f"📊 满级容量达到 {calculate_capacity(30):,} 个家丁位置，足以支撑大规模庄园运作喵～")
print()
