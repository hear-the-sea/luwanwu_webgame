"""
门客招募随机波动单元测试
"""
import random
from django.test import TestCase
from guests.utils.recruitment_variance import (
    apply_recruitment_variance,
    calculate_talent_grade,
    ATTRIBUTE_VARIANCE_CONFIG,
    MAX_GROWABLE_ATTRIBUTE,
)


class TestRecruitmentVariance(TestCase):
    """招募随机波动单元测试"""

    def setUp(self):
        """测试前准备"""
        # 绿色武将模板
        self.green_military_template = {
            "force": 52,
            "intellect": 21,
            "defense": 59,
            "agility": 43,
            "luck": 45,
        }

        # 橙色文官模板
        self.orange_civil_template = {
            "force": 44,
            "intellect": 75,
            "defense": 73,
            "agility": 53,
            "luck": 130,
        }

    def test_total_points_unchanged(self):
        """测试：四维总点数保持不变"""
        rng = random.Random(42)

        for _ in range(50):  # 多次测试
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )

            growable = ["force", "intellect", "defense", "agility"]
            original_total = sum(self.green_military_template[attr] for attr in growable)
            result_total = sum(result[attr] for attr in growable)

            self.assertEqual(
                result_total,
                original_total,
                f"四维总点应保持{original_total}，但得到{result_total}"
            )

    def test_single_attribute_bounds(self):
        """测试：单个属性在合理范围内"""
        rng = random.Random(42)

        for _ in range(50):
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )

            for attr in ["force", "intellect", "defense", "agility"]:
                base_value = self.green_military_template[attr]
                result_value = result[attr]

                # 约束1：不低于88%
                min_value = int(base_value * ATTRIBUTE_VARIANCE_CONFIG["min_ratio"])
                self.assertGreaterEqual(
                    result_value,
                    min_value,
                    f"{attr}={result_value}低于最小值{min_value}"
                )

                # 约束2：不超过112%
                max_value = int(base_value * ATTRIBUTE_VARIANCE_CONFIG["max_ratio"])
                self.assertLessEqual(
                    result_value,
                    max_value,
                    f"{attr}={result_value}超过最大值{max_value}"
                )

                # 约束3：可成长属性 < 100
                self.assertLess(
                    result_value,
                    MAX_GROWABLE_ATTRIBUTE,
                    f"{attr}={result_value}超过硬上限{MAX_GROWABLE_ATTRIBUTE}"
                )

    def test_luck_variance(self):
        """测试：运势在±5范围内波动"""
        rng = random.Random(42)

        luck_values = []
        for _ in range(100):
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )
            luck_values.append(result["luck"])

        base_luck = self.green_military_template["luck"]

        # 检查所有运势值都在合理范围
        for luck in luck_values:
            self.assertGreaterEqual(
                luck,
                base_luck - ATTRIBUTE_VARIANCE_CONFIG["luck_deviation"],
                f"运势{luck}低于下限"
            )
            self.assertLessEqual(
                luck,
                base_luck + ATTRIBUTE_VARIANCE_CONFIG["luck_deviation"],
                f"运势{luck}超过上限"
            )

        # 检查运势确实有分布（不是全部相同）
        unique_luck = set(luck_values)
        self.assertGreater(
            len(unique_luck),
            3,
            "运势波动范围过小，应该有多种不同值"
        )

    def test_attribute_diversity(self):
        """测试：多次生成产生不同的属性组合"""
        rng = random.Random(42)

        results = []
        for _ in range(20):
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )
            # 将属性组合转为元组用于去重
            combo = tuple(result[attr] for attr in ["force", "intellect", "defense", "agility"])
            results.append(combo)

        unique_combos = set(results)
        self.assertGreater(
            len(unique_combos),
            10,
            f"20次生成应该有超过10种不同组合，实际{len(unique_combos)}种"
        )

    def test_orange_civil_high_stats(self):
        """测试：橙色文官高属性不会超界"""
        rng = random.Random(42)

        for _ in range(50):
            result = apply_recruitment_variance(
                self.orange_civil_template,
                "orange",
                "civil",
                rng
            )

            # 橙色文官智力75、防御73，波动后可能接近上限
            for attr in ["force", "intellect", "defense", "agility"]:
                self.assertLess(
                    result[attr],
                    MAX_GROWABLE_ATTRIBUTE,
                    f"橙色文官{attr}={result[attr]}超过硬上限"
                )

    def test_deterministic_with_seed(self):
        """测试：相同种子产生相同结果"""
        rng1 = random.Random(12345)
        result1 = apply_recruitment_variance(
            self.green_military_template,
            "green",
            "military",
            rng1
        )

        rng2 = random.Random(12345)
        result2 = apply_recruitment_variance(
            self.green_military_template,
            "green",
            "military",
            rng2
        )

        self.assertEqual(result1, result2, "相同种子应产生相同结果")

    def test_talent_grade_calculation(self):
        """测试：资质评级计算"""
        # 由于固定总点，当前都应该返回normal
        result = apply_recruitment_variance(
            self.green_military_template,
            "green",
            "military",
            random.Random(42)
        )

        base_total = sum(
            self.green_military_template[attr]
            for attr in ["force", "intellect", "defense", "agility"]
        )

        grade = calculate_talent_grade(result, base_total)
        self.assertEqual(grade, "normal")

    def test_minimum_attribute_values(self):
        """测试：所有属性值至少为1"""
        rng = random.Random(42)

        for _ in range(50):
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )

            for attr, value in result.items():
                self.assertGreaterEqual(
                    value,
                    1,
                    f"属性{attr}={value}不应小于1"
                )

    def test_extreme_distribution_prevented(self):
        """测试：防止极端分布（某项过低或过高）"""
        rng = random.Random(42)

        for _ in range(50):
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )

            # 检查没有属性偏离模板过远
            for attr in ["force", "intellect", "defense", "agility"]:
                base = self.green_military_template[attr]
                value = result[attr]
                ratio = value / base

                self.assertGreaterEqual(
                    ratio,
                    0.85,
                    f"{attr}偏离模板过低：{value}/{base}={ratio:.2f}"
                )
                self.assertLessEqual(
                    ratio,
                    1.15,
                    f"{attr}偏离模板过高：{value}/{base}={ratio:.2f}"
                )

    def test_statistical_distribution(self):
        """测试：统计分布合理"""
        rng = random.Random(42)

        force_values = []
        for _ in range(200):
            result = apply_recruitment_variance(
                self.green_military_template,
                "green",
                "military",
                rng
            )
            force_values.append(result["force"])

        # 计算平均值和标准差
        avg_force = sum(force_values) / len(force_values)
        base_force = self.green_military_template["force"]

        # 平均值应该接近模板值（允许±2的偏差）
        self.assertAlmostEqual(
            avg_force,
            base_force,
            delta=2.0,
            msg=f"武力平均值{avg_force}应接近模板值{base_force}"
        )

        # 应该有足够的分散度
        variance = sum((x - avg_force) ** 2 for x in force_values) / len(force_values)
        std_dev = variance ** 0.5

        self.assertGreater(
            std_dev,
            0.5,
            "武力标准差应该大于0.5，表明有足够的随机性"
        )
