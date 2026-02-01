#!/usr/bin/env python
"""
招募概率测试脚本

用于测试和统计门客招募系统的稀有度概率分布。
可以验证实际概率是否符合预期设计值。

使用方法:
    python manage.py shell < scripts/test_recruitment_probability.py

    或者在 Django shell 中执行:
    from pathlib import Path
    exec(Path('scripts/test_recruitment_probability.py').read_text())
"""
from __future__ import annotations

import random
import sys
import time
from collections import Counter
from typing import Dict

# 导入招募系统模块
from guests.utils.recruitment_utils import (
    RARITY_DISTRIBUTION,
    RARITY_ORDER,
    TOTAL_WEIGHT,
    choose_rarity,
)
from guests.models import GuestRarity

# 稀有度中文名称映射
RARITY_NAMES = {
    GuestRarity.BLACK: "黑",
    GuestRarity.GRAY: "灰",
    GuestRarity.GREEN: "绿",
    GuestRarity.BLUE: "蓝",
    GuestRarity.RED: "红",
    GuestRarity.PURPLE: "紫",
    GuestRarity.ORANGE: "橙",
}

# 预期概率（从 RARITY_DISTRIBUTION 计算）
EXPECTED_RATES: Dict[str, float] = {}
for rarity, weight in RARITY_DISTRIBUTION:
    EXPECTED_RATES[rarity] = weight / TOTAL_WEIGHT * 100


def run_simulation(
    iterations: int = 100000,
    seed: int | None = None,
    verbose: bool = True,
) -> Dict[str, int]:
    """
    运行招募概率模拟测试。

    Args:
        iterations: 模拟次数
        seed: 随机数种子（可选，用于可重复测试）
        verbose: 是否输出详细信息

    Returns:
        各稀有度的抽取次数统计
    """
    rng = random.Random(seed)
    counter: Counter[str] = Counter()

    if verbose:
        print(f"\n{'='*60}")
        print(f"招募概率测试 - 模拟 {iterations:,} 次抽取")
        print(f"{'='*60}")
        if seed is not None:
            print(f"随机种子: {seed}")
        print()

    start_time = time.time()

    # 进度显示
    progress_interval = max(1, iterations // 20)
    for i in range(iterations):
        rarity = choose_rarity(rng)
        counter[rarity] += 1

        if verbose and (i + 1) % progress_interval == 0:
            progress = (i + 1) / iterations * 100
            sys.stdout.write(f"\r进度: {progress:.0f}% ({i+1:,}/{iterations:,})")
            sys.stdout.flush()

    elapsed = time.time() - start_time

    if verbose:
        sys.stdout.write("\r" + " " * 50 + "\r")  # 清除进度行
        print(f"模拟完成！耗时: {elapsed:.2f} 秒\n")

    return dict(counter)


def analyze_results(
    results: Dict[str, int],
    iterations: int,
    verbose: bool = True,
) -> Dict[str, Dict[str, float]]:
    """
    分析模拟结果并与预期概率对比。

    Args:
        results: 各稀有度抽取次数
        iterations: 总模拟次数
        verbose: 是否输出详细信息

    Returns:
        分析结果字典
    """
    analysis = {}

    if verbose:
        print(f"{'稀有度':<8} {'抽取次数':>12} {'实际概率':>12} {'预期概率':>12} {'偏差':>10}")
        print("-" * 60)

    # 按稀有度顺序（从高到低）显示
    display_order = list(reversed(RARITY_ORDER))

    for rarity in display_order:
        count = results.get(rarity, 0)
        actual_rate = count / iterations * 100
        expected_rate = EXPECTED_RATES.get(rarity, 0)
        deviation = actual_rate - expected_rate

        # 计算相对偏差
        if expected_rate > 0:
            relative_deviation = deviation / expected_rate * 100
        else:
            relative_deviation = 0

        analysis[rarity] = {
            "count": count,
            "actual_rate": actual_rate,
            "expected_rate": expected_rate,
            "deviation": deviation,
            "relative_deviation": relative_deviation,
        }

        if verbose:
            name = RARITY_NAMES.get(rarity, rarity)
            deviation_str = f"{deviation:+.4f}%"
            if abs(relative_deviation) > 20:
                deviation_str += " ⚠️"
            print(
                f"{name:<8} {count:>12,} {actual_rate:>11.4f}% {expected_rate:>11.4f}% {deviation_str:>10}"
            )

    if verbose:
        print("-" * 60)
        total = sum(results.values())
        print(f"{'总计':<8} {total:>12,}")
        print()

    return analysis


def run_batch_test(
    batch_count: int = 10,
    iterations_per_batch: int = 100000,
    verbose: bool = True,
) -> None:
    """
    运行多批次测试，统计概率稳定性。

    Args:
        batch_count: 批次数量
        iterations_per_batch: 每批次模拟次数
        verbose: 是否输出详细信息
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"批次测试 - {batch_count} 批 x {iterations_per_batch:,} 次")
        print(f"{'='*60}\n")

    batch_results: Dict[str, list] = {rarity: [] for rarity in RARITY_ORDER}

    for batch in range(batch_count):
        if verbose:
            print(f"批次 {batch + 1}/{batch_count}...")

        results = run_simulation(
            iterations=iterations_per_batch,
            seed=None,
            verbose=False,
        )

        for rarity in RARITY_ORDER:
            rate = results.get(rarity, 0) / iterations_per_batch * 100
            batch_results[rarity].append(rate)

    if verbose:
        print(f"\n{'稀有度':<8} {'预期概率':>12} {'平均值':>12} {'最小值':>12} {'最大值':>12} {'标准差':>10}")
        print("-" * 70)

        display_order = list(reversed(RARITY_ORDER))
        for rarity in display_order:
            rates = batch_results[rarity]
            expected = EXPECTED_RATES.get(rarity, 0)
            avg = sum(rates) / len(rates)
            min_val = min(rates)
            max_val = max(rates)
            std_dev = (sum((r - avg) ** 2 for r in rates) / len(rates)) ** 0.5

            name = RARITY_NAMES.get(rarity, rarity)
            print(
                f"{name:<8} {expected:>11.4f}% {avg:>11.4f}% {min_val:>11.4f}% {max_val:>11.4f}% {std_dev:>9.4f}%"
            )

        print("-" * 70)
        print()


def print_expected_rates() -> None:
    """打印预期概率配置。"""
    print(f"\n{'='*60}")
    print("预期概率配置")
    print(f"{'='*60}")
    print(f"总权重: {TOTAL_WEIGHT:,}\n")

    print(f"{'稀有度':<8} {'权重':>12} {'概率':>12} {'期望次数(万抽)':>15}")
    print("-" * 50)

    display_order = list(reversed(RARITY_ORDER))
    for rarity in display_order:
        weight = 0
        for r, w in RARITY_DISTRIBUTION:
            if r == rarity:
                weight = w
                break

        rate = weight / TOTAL_WEIGHT * 100
        expected_per_10k = weight / TOTAL_WEIGHT * 10000
        name = RARITY_NAMES.get(rarity, rarity)
        print(f"{name:<8} {weight:>12,} {rate:>11.4f}% {expected_per_10k:>14.1f}")

    print("-" * 50)
    total_weight = sum(w for _, w in RARITY_DISTRIBUTION)
    print(f"{'总计':<8} {total_weight:>12,} {100:>11.4f}%")
    print()


def main():
    """主函数。"""
    print_expected_rates()

    # 单次大规模测试
    results = run_simulation(iterations=1000000, seed=None, verbose=True)
    analyze_results(results, iterations=1000000, verbose=True)

    # 批次稳定性测试
    run_batch_test(batch_count=10, iterations_per_batch=100000, verbose=True)

    print("测试完成！")


if __name__ == "__main__":
    main()
