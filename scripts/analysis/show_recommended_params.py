#!/usr/bin/env python3
"""
展示推荐方案的各级详细数据
"""
import math


def show_level_details(name, base_cost, cost_growth, base_time, time_growth, max_level, grain_ratio=0):
    """展示各级详细数据"""
    print(f"\n{'=' * 80}")
    print(f"{name}")
    print(f"{'=' * 80}")
    print("\n参数配置:")
    print(f"  base_cost: {base_cost:,} 银两")
    print(f"  cost_growth: {cost_growth}")
    print(f"  base_time: {base_time}s ({base_time/3600:.1f}小时 / {base_time/86400:.2f}天)")
    print(f"  time_growth: {time_growth}")
    if grain_ratio > 0:
        print(f"  grain_cost: 银两的{grain_ratio*100:.0f}%")
    print()

    total_cost = 0
    total_time = 0
    total_grain = 0

    print(f"{'等级':<6} {'升级成本':>15} {'升级时间':>20} {'累计成本':>20} {'累计时间':>15}")
    print("-" * 90)

    for level in range(1, max_level + 1):
        cost_multiplier = cost_growth ** (level - 1)
        time_multiplier = time_growth ** (level - 1)

        cost = math.ceil(base_cost * cost_multiplier)
        duration = math.ceil(base_time * time_multiplier)

        total_cost += cost
        total_time += duration

        if grain_ratio > 0:
            grain = math.ceil(base_cost * grain_ratio * cost_multiplier)
            total_grain += grain
            cost_str = f"{cost:,}银 + {grain:,}粮"
        else:
            cost_str = f"{cost:,}银两"

        # 格式化升级时间
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

        # 格式化累计成本
        if grain_ratio > 0:
            total_cost_str = f"{total_cost:,}银 + {total_grain:,}粮"
        else:
            total_cost_str = f"{total_cost:,}银"

        print(f"Lv{level:<4} {cost_str:>22} {duration_str:>20} {total_cost_str:>27} {total_time_str:>15}")

    print("-" * 90)
    print("\n📊 总计:")
    if grain_ratio > 0:
        print(f"  总成本: {total_cost:,} 银两 + {total_grain:,} 粮食")
    else:
        print(f"  总成本: {total_cost:,} 银两")
    print(f"  总时长: {total_time/86400:.1f} 天 ({total_time/3600:.0f} 小时)")
    print(f"  最后一级成本: {cost:,} 银两")

    return {
        "total_cost": total_cost,
        "total_grain": total_grain,
        "total_time_days": total_time / 86400,
        "last_level_cost": cost,
    }


print("=" * 80)
print("推荐方案详细数据")
print("=" * 80)
print()
print("根据「最后一级2000万银两 + 总时长6个月」目标")
print("以下方案综合得分最优，且前期体验友好")
print()

# 聚贤庄推荐方案
juxian_result = show_level_details(
    "聚贤庄 (Lv20) - 推荐方案", base_cost=800, cost_growth=1.70, base_time=3600, time_growth=1.46, max_level=20
)

# 悠嘻宝塔推荐方案
youxi_result = show_level_details(
    "悠嘻宝塔 (Lv6) - 推荐方案",
    base_cost=50000,
    cost_growth=3.3,
    base_time=129600,
    time_growth=2.3,
    max_level=6,
    grain_ratio=0.2,
)

# 综合评估
print(f"\n{'=' * 80}")
print("综合评估")
print(f"{'=' * 80}")
print()
print("✅ 前期体验:")
print("  - 聚贤庄 Lv1: 800银两 + 1小时 (非常友好)")
print("  - 悠嘻宝塔 Lv1: 5万银+1万粮 + 1.5天 (适中)")
print()
print("✅ 后期挑战:")
print(f"  - 聚贤庄 Lv20: {juxian_result['last_level_cost']:,}银两 + {juxian_result['total_time_days']:.1f}天 (达标)")
print(f"  - 悠嘻宝塔 Lv6: {youxi_result['last_level_cost']:,}银两 + {youxi_result['total_time_days']:.1f}天 (达标)")
print()
print("✅ 曲线设计:")
print("  - 前期增长平缓，玩家容易上手")
print("  - 中期开始加速，体现指数增长")
print("  - 后期陡峭，形成长期目标")
print()
print("💰 付费空间:")
print(f"  - 两建筑总银两: {(juxian_result['total_cost'] + youxi_result['total_cost']):,}")
print(f"  - 两建筑总时长: {max(juxian_result['total_time_days'], youxi_result['total_time_days']):.1f}天 (并行)")
print("  - 银两加速机制可大幅缩短等待时间")
print("  - 最后几级是最大付费动力点")
print()
