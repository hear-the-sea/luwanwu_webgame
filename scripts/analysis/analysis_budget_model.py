#!/usr/bin/env python3
"""
全局预算模型 - 验证"一年全勤满级"的可行性
"""
import math
from typing import Dict, List

import yaml

# ==================== 常量定义 ====================

# 建筑最大等级（从 gameplay/constants.py）
BUILDING_MAX_LEVELS = {
    "citang": 5,
    "youxibaota": 6,
    "treasury": 20,  # 调整后：从30降到20
    "silver_vault": 20,
    "granary": 20,
    "bathhouse": 20,
    "latrine": 20,
    "tavern": 10,
    "lianggongchang": 10,
    "ranch": 10,
    "smithy": 10,
    "stable": 10,
    "forge": 10,
}

# 祠堂缩时参数（从 gameplay/models.py）
CITANG_BUILDING_TIME_REDUCTION_PER_LEVEL = 0.05  # 每级减少5%建筑时间

# 并发上限
MAX_CONCURRENT_BUILDING_UPGRADES = 2
MAX_CONCURRENT_TECH_UPGRADES = 2

# 初始资源（从 gameplay/constants.py）
INITIAL_GRAIN = 1200
INITIAL_SILVER = 500

# ==================== 数据加载 ====================


def load_building_data() -> List[dict]:
    """加载建筑配置"""
    with open("data/building_templates.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["buildings"]


def load_technology_data() -> List[dict]:
    """加载科技配置"""
    with open("data/technology_templates.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["technologies"]


# ==================== 计算函数 ====================


def calc_building_upgrade_cost(building: dict, target_level: int) -> Dict[str, int]:
    """计算建筑升级到目标等级的成本"""
    base_cost = building["base_cost"]
    cost_growth = building["cost_growth"]
    multiplier = cost_growth ** (target_level - 1)

    return {resource: math.ceil(amount * multiplier) for resource, amount in base_cost.items()}


def calc_building_upgrade_time(building: dict, target_level: int, citang_level: int = 0) -> int:
    """计算建筑升级到目标等级的时间（秒）"""
    base_time = building["base_upgrade_time"]
    time_growth = building["time_growth"]
    multiplier = time_growth ** (target_level - 1)

    base_duration = math.ceil(base_time * multiplier)

    # 应用祠堂缩时
    time_reduction = citang_level * CITANG_BUILDING_TIME_REDUCTION_PER_LEVEL
    actual_duration = max(1, int(base_duration * (1 - time_reduction)))

    return actual_duration


def calc_tech_upgrade_cost(tech: dict, next_level: int) -> int:
    """计算科技升级到下一级的成本（只消耗银两）"""
    base_cost = tech["base_cost"]
    # 公式: base_cost * (next_level ** 2) * 5
    return base_cost * (next_level**2) * 5


def calc_tech_upgrade_time(current_level: int) -> int:
    """计算科技升级时间（秒）"""
    # 公式: 60 * (1.4 ** level)
    return int(60 * (1.4**current_level))


# ==================== 升级路径模拟 ====================


def simulate_building_upgrades(buildings: List[dict]) -> dict:
    """模拟建筑升级全过程"""
    total_silver = 0
    total_grain = 0
    total_time_sequential = 0  # 顺序升级总耗时

    building_details = []

    for building in buildings:
        key = building["key"]
        max_level = BUILDING_MAX_LEVELS.get(key, 20)  # 默认20级

        silver = 0
        grain = 0
        time = 0

        for level in range(1, max_level + 1):
            cost = calc_building_upgrade_cost(building, level)
            duration = calc_building_upgrade_time(building, level, citang_level=0)  # 先不考虑祠堂

            silver += cost.get("silver", 0)
            grain += cost.get("grain", 0)
            time += duration

        building_details.append(
            {
                "key": key,
                "name": building["name"],
                "max_level": max_level,
                "total_silver": silver,
                "total_grain": grain,
                "total_time_seconds": time,
                "total_time_hours": time / 3600,
                "total_time_days": time / 86400,
            }
        )

        total_silver += silver
        total_grain += grain
        total_time_sequential += time

    return {
        "total_silver": total_silver,
        "total_grain": total_grain,
        "total_time_sequential_seconds": total_time_sequential,
        "total_time_sequential_hours": total_time_sequential / 3600,
        "total_time_sequential_days": total_time_sequential / 86400,
        "total_time_parallel_days": total_time_sequential / 86400 / MAX_CONCURRENT_BUILDING_UPGRADES,
        "building_count": len(buildings),
        "details": building_details,
    }


def simulate_technology_upgrades(technologies: List[dict], max_days_threshold: float = 100.0) -> dict:
    """模拟科技升级全过程

    Args:
        technologies: 科技列表
        max_days_threshold: 单个科技总耗时超过此值视为"不可达"（天）
    """
    total_silver = 0
    total_time_sequential = 0

    tech_details = []
    unreachable_techs = []

    for tech in technologies:
        max_level = tech["max_level"]

        silver = 0
        time = 0

        for level in range(0, max_level):
            cost = calc_tech_upgrade_cost(tech, level + 1)
            duration = calc_tech_upgrade_time(level)

            silver += cost
            time += duration

        time_days = time / 86400

        tech_info = {
            "key": tech["key"],
            "name": tech["name"],
            "max_level": max_level,
            "total_silver": silver,
            "total_time_seconds": time,
            "total_time_hours": time / 3600,
            "total_time_days": time_days,
        }

        if time_days > max_days_threshold:
            tech_info["is_reachable"] = False
            unreachable_techs.append(tech_info)
        else:
            tech_info["is_reachable"] = True
            tech_details.append(tech_info)
            total_silver += silver
            total_time_sequential += time

    return {
        "total_silver": total_silver,
        "total_time_sequential_seconds": total_time_sequential,
        "total_time_sequential_hours": total_time_sequential / 3600,
        "total_time_sequential_days": total_time_sequential / 86400,
        "total_time_parallel_days": total_time_sequential / 86400 / MAX_CONCURRENT_TECH_UPGRADES,
        "tech_count": len(technologies),
        "reachable_count": len(tech_details),
        "unreachable_count": len(unreachable_techs),
        "details": tech_details,
        "unreachable": unreachable_techs,
    }


# ==================== 资源产出评估 ====================


def calc_building_production_at_level(building: dict, level: int) -> float:
    """计算建筑在指定等级的每小时产量"""
    base_rate = building["base_rate_per_hour"]
    rate_growth = building["rate_growth"]

    growth = 1 + rate_growth * (level - 1)
    return base_rate * growth


def estimate_resource_production() -> dict:
    """评估资源产出速率"""
    buildings = load_building_data()

    # 假设建筑在升级过程中的平均等级（粗略估算）
    avg_level = 10

    grain_per_hour = 0
    silver_per_hour = 0

    for building in buildings:
        resource_type = building.get("resource_type")
        production = calc_building_production_at_level(building, avg_level)

        if resource_type == "grain":
            grain_per_hour += production
            # 茅厕额外产等量银两
            if building["key"] == "latrine":
                silver_per_hour += production
        elif resource_type == "silver":
            silver_per_hour += production

    return {
        "grain_per_hour": grain_per_hour,
        "silver_per_hour": silver_per_hour,
        "grain_per_day": grain_per_hour * 24,
        "silver_per_day": silver_per_hour * 24,
    }


# ==================== 主分析函数 ====================
# ==================== 主分析函数 ====================


def _print_separator(title: str | None = None) -> None:
    print("=" * 80)
    if title:
        print(title)
        print("=" * 80)


def _print_overview(buildings: List[dict], technologies: List[dict]) -> None:
    print("📊 数据概览:")
    print(f"  - 建筑总数: {len(buildings)}")
    print(f"  - 科技总数: {len(technologies)}")
    print()


def _print_building_analysis(building_result: dict) -> None:
    _print_separator("🏗️  建筑升级预算分析")

    print("\n总资源消耗:")
    print(f"  - 银两: {building_result['total_silver']:,}")
    print(f"  - 粮食: {building_result['total_grain']:,}")
    print("\n总时长分析:")
    print(f"  - 顺序升级总耗时: {building_result['total_time_sequential_days']:.1f} 天")
    print(
        f"  - 并发{MAX_CONCURRENT_BUILDING_UPGRADES}个施工队耗时: {building_result['total_time_parallel_days']:.1f} 天"
    )

    print("\n最耗时的建筑 TOP 5:")
    sorted_buildings = sorted(building_result["details"], key=lambda x: x["total_time_days"], reverse=True)
    for index, building in enumerate(sorted_buildings[:5], 1):
        print(f"  {index}. {building['name']} (Lv{building['max_level']}): {building['total_time_days']:.2f} 天")

    print("\n最耗资源的建筑 TOP 5 (按银两):")
    sorted_by_silver = sorted(building_result["details"], key=lambda x: x["total_silver"], reverse=True)
    for index, building in enumerate(sorted_by_silver[:5], 1):
        print(
            f"  {index}. {building['name']} (Lv{building['max_level']}): "
            f"{building['total_silver']:,} 银两, {building['total_grain']:,} 粮食"
        )


def _print_tech_analysis(tech_result: dict) -> None:
    print()
    _print_separator("🔬 科技升级预算分析")

    if tech_result["unreachable_count"] > 0:
        print(f"\n⚠️  发现 {tech_result['unreachable_count']} 个不可达科技（单个总耗时 > 100天）:")
        for tech in tech_result["unreachable"]:
            print(
                f"   ❌ {tech['name']} (Lv{tech['max_level']}): {tech['total_time_days']:.2f} 天 ({tech['total_silver']:,} 银两)"
            )
        print(f"\n✅ 可达科技数量: {tech_result['reachable_count']} / {tech_result['tech_count']}")

    print("\n总资源消耗（仅计算可达科技）:")
    print(f"  - 银两: {tech_result['total_silver']:,}")
    print("\n总时长分析（仅计算可达科技）:")
    print(f"  - 顺序研究总耗时: {tech_result['total_time_sequential_days']:.1f} 天")
    print(f"  - 并发{MAX_CONCURRENT_TECH_UPGRADES}个科研槽耗时: {tech_result['total_time_parallel_days']:.1f} 天")

    print("\n最耗时的科技 TOP 10 (可达):")
    sorted_techs = sorted(tech_result["details"], key=lambda x: x["total_time_days"], reverse=True)
    for index, tech in enumerate(sorted_techs[:10], 1):
        print(
            f"  {index}. {tech['name']} (Lv{tech['max_level']}): {tech['total_time_days']:.2f} 天 ({tech['total_silver']:,} 银两)"
        )


def _calc_combined_metrics(building_result: dict, tech_result: dict) -> dict:
    total_silver = building_result["total_silver"] + tech_result["total_silver"]
    total_grain = building_result["total_grain"]
    total_time_days = max(building_result["total_time_parallel_days"], tech_result["total_time_parallel_days"])
    return {
        "total_silver": total_silver,
        "total_grain": total_grain,
        "total_time_days": total_time_days,
    }


def _print_combined_analysis(building_result: dict, tech_result: dict, combined: dict) -> None:
    print()
    _print_separator("📈 综合预算分析")

    print("\n总资源需求:")
    print(f"  - 银两: {combined['total_silver']:,}")
    print(f"  - 粮食: {combined['total_grain']:,}")

    print("\n总时长需求（建筑与科技并行）:")
    print(f"  - 建筑: {building_result['total_time_parallel_days']:.1f} 天")
    print(f"  - 科技: {tech_result['total_time_parallel_days']:.1f} 天")
    print(f"  - 瓶颈: {combined['total_time_days']:.1f} 天")


def _print_production_analysis(combined: dict, production: dict) -> dict:
    print()
    _print_separator("💰 资源产出评估")

    print("\n建筑产出（假设平均Lv10）:")
    print(f"  - 粮食: {production['grain_per_hour']:.0f} /小时 ({production['grain_per_day']:.0f} /天)")
    print(f"  - 银两: {production['silver_per_hour']:.0f} /小时 ({production['silver_per_day']:.0f} /天)")

    days_to_break_even_grain = (
        combined["total_grain"] / production["grain_per_day"] if production["grain_per_day"] > 0 else float("inf")
    )
    days_to_break_even_silver = (
        combined["total_silver"] / production["silver_per_day"] if production["silver_per_day"] > 0 else float("inf")
    )

    print("\n仅靠建筑产出回本时间:")
    print(f"  - 粮食: {days_to_break_even_grain:.1f} 天")
    print(f"  - 银两: {days_to_break_even_silver:.1f} 天")

    return {
        "days_to_break_even_grain": days_to_break_even_grain,
        "days_to_break_even_silver": days_to_break_even_silver,
    }


def _print_feasibility(combined: dict, production: dict) -> dict:
    print()
    _print_separator("🎯 一年全勤满级可行性评估")

    one_year_days = 365
    total_time_days = combined["total_time_days"]
    total_grain = combined["total_grain"]
    total_silver = combined["total_silver"]

    print("\n时间维度:")
    print(f"  - 升级总耗时: {total_time_days:.1f} 天")
    print(f"  - 一年可用时间: {one_year_days} 天")
    print(f"  - 时间占用率: {total_time_days / one_year_days * 100:.1f}%")

    if total_time_days <= one_year_days:
        print(f"  ✅ 时间充足，还剩 {one_year_days - total_time_days:.1f} 天")
    else:
        print(f"  ❌ 时间不足，缺少 {total_time_days - one_year_days:.1f} 天")

    print("\n资源维度（仅建筑产出）:")
    print(f"  - 粮食需求: {total_grain:,}")
    print(f"  - 一年产出: {production['grain_per_day'] * one_year_days:,.0f}")
    print(f"  - 银两需求: {total_silver:,}")
    print(f"  - 一年产出: {production['silver_per_day'] * one_year_days:,.0f}")

    grain_sufficient = production["grain_per_day"] * one_year_days >= total_grain
    silver_sufficient = production["silver_per_day"] * one_year_days >= total_silver

    if grain_sufficient:
        print("  ✅ 粮食充足")
    else:
        deficit = total_grain - production["grain_per_day"] * one_year_days
        print(f"  ❌ 粮食不足，缺口: {deficit:,.0f}")

    if silver_sufficient:
        print("  ✅ 银两充足")
    else:
        deficit = total_silver - production["silver_per_day"] * one_year_days
        print(f"  ❌ 银两不足，缺口: {deficit:,.0f}")

    return {
        "grain_sufficient": grain_sufficient,
        "silver_sufficient": silver_sufficient,
        "one_year_days": one_year_days,
    }


def _print_conclusion(
    building_result: dict, tech_result: dict, combined: dict, production: dict, feasibility: dict
) -> None:
    print()
    _print_separator("💡 结论与建议")
    print()

    print("📌 关键发现:")
    print()
    print("1️⃣  不可达科技问题:")
    if tech_result["unreachable_count"] > 0:
        print(f"   ⚠️  {tech_result['unreachable_count']} 个科技配置的max_level过高，导致指数公式爆炸")
        for tech in tech_result["unreachable"]:
            print(f"      - {tech['name']}: max_level={tech['max_level']} → 需要 {tech['total_time_days']:.0f} 天")
        print("   💡 建议：降低max_level或修改时间公式（从指数改为幂函数）")
    else:
        print("   ✅ 所有科技均在可达范围内")

    print()
    print("2️⃣  可达内容的可行性:")
    total_time_days = combined["total_time_days"]
    one_year_days = feasibility["one_year_days"]
    grain_sufficient = feasibility["grain_sufficient"]
    silver_sufficient = feasibility["silver_sufficient"]

    if total_time_days <= one_year_days and grain_sufficient and silver_sufficient:
        print("   ✅ 全勤玩家一年可以达到全建筑和所有可达科技满级")
        print(f"   📊 时间占用率: {total_time_days / one_year_days * 100:.1f}%")
        print("   💰 资源充足，粮食和银两产出均满足需求")
    else:
        print("   ⚠️  存在瓶颈:")
        if total_time_days > one_year_days:
            print(
                f"      ⏰ 时间不足: {total_time_days:.1f}天 > {one_year_days}天，缺口 {total_time_days - one_year_days:.1f}天"
            )
        else:
            print(
                f"      ✅ 时间充足: {total_time_days:.1f}天 < {one_year_days}天，还剩 {one_year_days - total_time_days:.1f}天"
            )

        if not grain_sufficient:
            deficit = combined["total_grain"] - production["grain_per_day"] * one_year_days
            print(f"      🌾 粮食不足: 缺口 {deficit:,.0f}，需要额外来源（任务/战斗）")
        else:
            print("      ✅ 粮食充足")

        if not silver_sufficient:
            deficit = combined["total_silver"] - production["silver_per_day"] * one_year_days
            print(f"      💰 银两不足: 缺口 {deficit:,.0f}，需要额外来源（任务/战斗/打工）")
        else:
            print("      ✅ 银两充足")

    print()
    print("3️⃣  藏宝阁30级的特殊性:")
    treasury_detail = next((b for b in building_result["details"] if b["key"] == "treasury"), None)
    if treasury_detail:
        print("   ⚠️  藏宝阁单个建筑占据:")
        print(
            "      - 时间: "
            f"{treasury_detail['total_time_days']:.1f}天 "
            f"(占建筑总时长 {treasury_detail['total_time_days'] / building_result['total_time_sequential_days'] * 100:.0f}%)"
        )
        print(
            "      - 银两: "
            f"{treasury_detail['total_silver']:,} "
            f"(占建筑总成本 {treasury_detail['total_silver'] / building_result['total_silver'] * 100:.0f}%)"
        )
        print("   💡 建议：考虑降低藏宝阁max_level或调整cost_growth参数")

    print()
    _print_separator("⚠️  分析局限性")
    print()
    print("本分析基于以下假设，实际情况可能有差异:")
    print("  ❌ 未考虑任务奖励、战斗掉落、打工收益等额外资源来源")
    print("  ❌ 未考虑祠堂升级后对建筑升级时间的累积加速效应")
    print("  ❌ 未考虑玩家策略（优先级升级顺序）对体验的影响")
    print("  ❌ 未考虑建筑等级提升对资源产出的动态增长")
    print("  ❌ 资源产出按平均Lv10估算，实际是动态增长过程")
    print()


def main():
    _print_separator("全局预算模型分析 - 验证「一年全勤满级」可行性")
    print()

    buildings = load_building_data()
    technologies = load_technology_data()
    _print_overview(buildings, technologies)

    building_result = simulate_building_upgrades(buildings)
    _print_building_analysis(building_result)

    tech_result = simulate_technology_upgrades(technologies, max_days_threshold=100.0)
    _print_tech_analysis(tech_result)

    combined = _calc_combined_metrics(building_result, tech_result)
    _print_combined_analysis(building_result, tech_result, combined)

    production = estimate_resource_production()
    _print_production_analysis(combined, production)

    feasibility = _print_feasibility(combined, production)
    _print_conclusion(building_result, tech_result, combined, production, feasibility)


if __name__ == "__main__":
    main()
