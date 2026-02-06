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
import django
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
django.setup()

import argparse  # noqa: E402

from gameplay.models import MissionRun  # noqa: E402


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

    # 显示基本信息
    print("\n📋 基本信息:")
    print(f"  庄园 ID: {run.manor_id}")
    print(f"  任务: {run.mission.name if run.mission else 'N/A'}")
    print(f"  状态: {run.status}")
    print(f"  出征时间: {run.started_at}")
    print(f"  返程时间: {run.return_at}")
    print(f"  是否撤退: {run.is_retreating}")

    # 显示出征配置
    loadout = run.troop_loadout or {}
    print("\n⚔️  出征护院配置:")
    if loadout:
        for key, count in loadout.items():
            print(f"  {key}: {count}")
    else:
        print("  (无)")

    # 显示战报信息
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

    # 显示损失数据
    losses = report.losses or {}
    attacker_losses = losses.get("attacker", {})
    defender_losses = losses.get("defender", {})

    print("\n💥 攻击方损失（attacker）:")
    attacker_casualties = attacker_losses.get("casualties", [])
    if attacker_casualties:
        # 检查是否有重复条目
        key_counts = {}
        for entry in attacker_casualties:
            key = entry.get("key", "unknown")
            key_counts[key] = key_counts.get(key, 0) + 1

        # 显示每个伤亡条目
        for entry in attacker_casualties:
            key = entry.get("key", "unknown")
            label = entry.get("label", "")
            lost = entry.get("lost", 0)
            is_duplicate = key_counts.get(key, 0) > 1
            duplicate_mark = " ⚠️  重复!" if is_duplicate else ""
            print(f"  - {key} ({label}): 损失 {lost}{duplicate_mark}")

        # 累加统计
        print("\n📊 累加统计:")
        total_by_key = {}
        for entry in attacker_casualties:
            key = entry.get("key", "unknown")
            lost = entry.get("lost", 0)
            total_by_key[key] = total_by_key.get(key, 0) + lost

        for key, total_lost in total_by_key.items():
            original = loadout.get(key, 0)
            surviving = max(0, original - total_lost) if original > 0 else "N/A"
            # 检测异常：累加损失超过原始数量
            is_abnormal = original > 0 and total_lost > original
            abnormal_mark = " ⚠️  异常!" if is_abnormal else ""

            print(f"  {key}:")
            print(f"    原始数量: {original}")
            print(f"    累加损失: {total_lost}")
            print(f"    应该剩余: {surviving}{abnormal_mark}")

            if is_abnormal:
                print(f"    ❌ 错误：累加损失 ({total_lost}) > 原始数量 ({original})")
    else:
        print("  (无)")

    # 显示防守方损失
    print("\n🛡️  防守方损失（defender）:")
    defender_casualties = defender_losses.get("casualties", [])
    if defender_casualties:
        for entry in defender_casualties:
            key = entry.get("key", "unknown")
            label = entry.get("label", "")
            lost = entry.get("lost", 0)
            print(f"  - {key} ({label}): 损失 {lost}")
    else:
        print("  (无)")

    # 显示战报中记录的护院数据
    attacker_troops = report.attacker_troops or {}
    print("\n📈 战报中攻击方护院数据:")
    if attacker_troops:
        for key, count in attacker_troops.items():
            print(f"  {key}: {count}")
    else:
        print("  (无)")

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
