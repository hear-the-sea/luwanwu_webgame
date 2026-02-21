"""
检查任务战报中的护院损失数据

用于诊断护院归还问题：
1. 检查 casualties 中是否有重复条目
2. 检查损失累加是否超过原始数量
3. 显示详细的战报数据

使用方法:
    python scripts/check_battle_report_troops.py <mission_run_id>
"""

import sys
from pathlib import Path

import django

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
django.setup()

import argparse  # noqa: E402

from gameplay.models import MissionRun  # noqa: E402


def _print_basic_info(run) -> None:
    print("\n📋 基本信息:")
    print(f"  庄园 ID: {run.manor_id}")
    print(f"  任务: {run.mission.name if run.mission else 'N/A'}")
    print(f"  状态: {run.status}")
    print(f"  出征时间: {run.started_at}")
    print(f"  返程时间: {run.return_at}")
    print(f"  是否撤退: {run.is_retreating}")


def _print_loadout(loadout: dict) -> None:
    print("\n⚔️  出征护院配置:")
    if not loadout:
        print("  (无)")
        return

    for key, count in loadout.items():
        print(f"  {key}: {count}")


def _casualty_key_counts(casualties: list[dict]) -> dict[str, int]:
    key_counts: dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key", "unknown")
        key_counts[key] = key_counts.get(key, 0) + 1
    return key_counts


def _print_attacker_casualties(casualties: list[dict]) -> None:
    key_counts = _casualty_key_counts(casualties)
    for entry in casualties:
        key = entry.get("key", "unknown")
        label = entry.get("label", "")
        lost = entry.get("lost", 0)
        duplicate_mark = " ⚠️  重复!" if key_counts.get(key, 0) > 1 else ""
        print(f"  - {key} ({label}): 损失 {lost}{duplicate_mark}")


def _sum_attacker_losses(casualties: list[dict]) -> dict[str, int]:
    total_by_key: dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key", "unknown")
        lost = entry.get("lost", 0)
        total_by_key[key] = total_by_key.get(key, 0) + lost
    return total_by_key


def _print_attacker_summary(loadout: dict, casualties: list[dict]) -> None:
    print("\n📊 累加统计:")
    total_by_key = _sum_attacker_losses(casualties)

    for key, total_lost in total_by_key.items():
        original = loadout.get(key, 0)
        surviving = max(0, original - total_lost) if original > 0 else "N/A"
        is_abnormal = original > 0 and total_lost > original
        abnormal_mark = " ⚠️  异常!" if is_abnormal else ""

        print(f"  {key}:")
        print(f"    原始数量: {original}")
        print(f"    累加损失: {total_lost}")
        print(f"    应该剩余: {surviving}{abnormal_mark}")
        if is_abnormal:
            print(f"    ❌ 错误：累加损失 ({total_lost}) > 原始数量 ({original})")


def _print_defender_casualties(casualties: list[dict]) -> None:
    print("\n🛡️  防守方损失（defender）:")
    if not casualties:
        print("  (无)")
        return

    for entry in casualties:
        key = entry.get("key", "unknown")
        label = entry.get("label", "")
        lost = entry.get("lost", 0)
        print(f"  - {key} ({label}): 损失 {lost}")


def _print_attacker_troops(report) -> None:
    attacker_troops = report.attacker_troops or {}
    print("\n📈 战报中攻击方护院数据:")
    if not attacker_troops:
        print("  (无)")
        return

    for key, count in attacker_troops.items():
        print(f"  {key}: {count}")


def check_mission_run(run_id: int):
    """检查任务运行记录的护院损失"""
    print("=" * 60)
    print(f"检查任务运行 ID: {run_id}")
    print("=" * 60)

    try:
        run = MissionRun.objects.select_related("manor", "mission").get(pk=run_id)
    except MissionRun.DoesNotExist:
        print(f"\n❌ 错误：未找到 MissionRun ID={run_id}")
        return

    _print_basic_info(run)

    loadout = run.troop_loadout or {}
    _print_loadout(loadout)

    report = run.battle_report
    if not report:
        print("\n⚠️  警告：该任务没有战报")
        return

    print("\n📜 战报信息:")
    print(f"  战报 ID: {report.id}")
    print(f"  对手: {report.opponent_name}")
    print(f"  战斗类型: {report.battle_type}")
    print(f"  胜者: {report.winner}")
    print(f"  回合数: {len(report.rounds)}")

    losses = report.losses or {}
    attacker_casualties = (losses.get("attacker", {}) or {}).get("casualties", [])
    defender_casualties = (losses.get("defender", {}) or {}).get("casualties", [])

    print("\n💥 攻击方损失（attacker）:")
    if attacker_casualties:
        _print_attacker_casualties(attacker_casualties)
        _print_attacker_summary(loadout, attacker_casualties)
    else:
        print("  (无)")

    _print_defender_casualties(defender_casualties)
    _print_attacker_troops(report)

    print("\n" + "=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检查任务战报中的护院损失数据")
    parser.add_argument("run_id", type=int, help="MissionRun ID")
    args = parser.parse_args()

    try:
        check_mission_run(args.run_id)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
