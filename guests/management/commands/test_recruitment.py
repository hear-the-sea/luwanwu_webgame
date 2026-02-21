"""
招募概率测试管理命令

用法:
    python manage.py test_recruitment              # 默认测试（100万次）
    python manage.py test_recruitment -n 500000    # 指定次数
    python manage.py test_recruitment --batch      # 批次测试
    python manage.py test_recruitment --seed 42    # 指定随机种子
"""

from __future__ import annotations

import random
import sys
import time
from collections import Counter
from typing import Dict

from django.core.management.base import BaseCommand

from guests.models import GuestRarity
from guests.utils.recruitment_utils import RARITY_DISTRIBUTION, RARITY_ORDER, TOTAL_WEIGHT, choose_rarity

RARITY_NAMES = {
    GuestRarity.BLACK: "黑",
    GuestRarity.GRAY: "灰",
    GuestRarity.GREEN: "绿",
    GuestRarity.BLUE: "蓝",
    GuestRarity.RED: "红",
    GuestRarity.PURPLE: "紫",
    GuestRarity.ORANGE: "橙",
}

EXPECTED_RATES: Dict[str, float] = {}
for rarity, weight in RARITY_DISTRIBUTION:
    EXPECTED_RATES[rarity] = weight / TOTAL_WEIGHT * 100


class Command(BaseCommand):
    help = "测试招募系统的概率分布"

    def add_arguments(self, parser):
        parser.add_argument(
            "-n",
            "--iterations",
            type=int,
            default=1000000,
            help="模拟次数（默认: 1000000）",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="随机数种子（用于可重复测试）",
        )
        parser.add_argument(
            "--batch",
            action="store_true",
            help="运行批次稳定性测试",
        )
        parser.add_argument(
            "--batch-count",
            type=int,
            default=10,
            help="批次数量（默认: 10）",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="静默模式，仅输出结果",
        )

    def handle(self, *args, **options):
        iterations = options["iterations"]
        seed = options["seed"]
        batch_mode = options["batch"]
        batch_count = options["batch_count"]
        verbose = not options["quiet"]

        self.print_expected_rates()

        if batch_mode:
            self.run_batch_test(batch_count, iterations // 10, verbose)
        else:
            results = self.run_simulation(iterations, seed, verbose)
            self.analyze_results(results, iterations, verbose)

        self.stdout.write(self.style.SUCCESS("\n测试完成！"))

    def print_expected_rates(self):
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("预期概率配置")
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"总权重: {TOTAL_WEIGHT:,}\n")

        self.stdout.write(f"{'稀有度':<8} {'权重':>12} {'概率':>12} {'期望次数(万抽)':>15}")
        self.stdout.write("-" * 50)

        display_order = list(reversed(RARITY_ORDER))
        for rarity in display_order:
            weight = next((w for r, w in RARITY_DISTRIBUTION if r == rarity), 0)
            rate = weight / TOTAL_WEIGHT * 100
            expected_per_10k = weight / TOTAL_WEIGHT * 10000
            name = RARITY_NAMES.get(rarity, rarity)
            self.stdout.write(f"{name:<8} {weight:>12,} {rate:>11.4f}% {expected_per_10k:>14.1f}")

        self.stdout.write("-" * 50)
        self.stdout.write("")

    def run_simulation(self, iterations: int, seed: int | None, verbose: bool) -> Dict[str, int]:
        rng = random.Random(seed)
        counter: Counter[str] = Counter()

        if verbose:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"招募概率测试 - 模拟 {iterations:,} 次抽取")
            self.stdout.write(f"{'='*60}")
            if seed is not None:
                self.stdout.write(f"随机种子: {seed}")
            self.stdout.write("")

        start_time = time.time()
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
            sys.stdout.write("\r" + " " * 50 + "\r")
            self.stdout.write(f"模拟完成！耗时: {elapsed:.2f} 秒\n")

        return dict(counter)

    def analyze_results(self, results: Dict[str, int], iterations: int, verbose: bool):
        if verbose:
            self.stdout.write(f"{'稀有度':<8} {'抽取次数':>12} {'实际概率':>12} {'预期概率':>12} {'偏差':>10}")
            self.stdout.write("-" * 60)

        display_order = list(reversed(RARITY_ORDER))

        for rarity in display_order:
            count = results.get(rarity, 0)
            actual_rate = count / iterations * 100
            expected_rate = EXPECTED_RATES.get(rarity, 0)
            deviation = actual_rate - expected_rate

            if expected_rate > 0:
                relative_deviation = deviation / expected_rate * 100
            else:
                relative_deviation = 0

            if verbose:
                name = RARITY_NAMES.get(rarity, rarity)
                deviation_str = f"{deviation:+.4f}%"
                if abs(relative_deviation) > 20:
                    deviation_str += " ⚠️"
                self.stdout.write(
                    f"{name:<8} {count:>12,} {actual_rate:>11.4f}% {expected_rate:>11.4f}% {deviation_str:>10}"
                )

        if verbose:
            self.stdout.write("-" * 60)
            total = sum(results.values())
            self.stdout.write(f"{'总计':<8} {total:>12,}")
            self.stdout.write("")

    def run_batch_test(self, batch_count: int, iterations_per_batch: int, verbose: bool):
        if verbose:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"批次测试 - {batch_count} 批 x {iterations_per_batch:,} 次")
            self.stdout.write(f"{'='*60}\n")

        batch_results: Dict[str, list] = {rarity: [] for rarity in RARITY_ORDER}

        for batch in range(batch_count):
            if verbose:
                self.stdout.write(f"批次 {batch + 1}/{batch_count}...")

            results = self.run_simulation(
                iterations=iterations_per_batch,
                seed=None,
                verbose=False,
            )

            for rarity in RARITY_ORDER:
                rate = results.get(rarity, 0) / iterations_per_batch * 100
                batch_results[rarity].append(rate)

        if verbose:
            self.stdout.write(
                f"\n{'稀有度':<8} {'预期概率':>12} {'平均值':>12} {'最小值':>12} {'最大值':>12} {'标准差':>10}"
            )
            self.stdout.write("-" * 70)

            display_order = list(reversed(RARITY_ORDER))
            for rarity in display_order:
                rates = batch_results[rarity]
                expected = EXPECTED_RATES.get(rarity, 0)
                avg = sum(rates) / len(rates)
                min_val = min(rates)
                max_val = max(rates)
                std_dev = (sum((r - avg) ** 2 for r in rates) / len(rates)) ** 0.5

                name = RARITY_NAMES.get(rarity, rarity)
                self.stdout.write(
                    f"{name:<8} {expected:>11.4f}% {avg:>11.4f}% {min_val:>11.4f}% {max_val:>11.4f}% {std_dev:>9.4f}%"
                )

            self.stdout.write("-" * 70)
