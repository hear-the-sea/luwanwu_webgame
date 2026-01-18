"""
护院配置数据巡检脚本

检查和修复 MissionRun 中的脏 troop_loadout 数据：
1. 检查是否存在玩家没有的护院类型（可能导致护院复制漏洞）
2. 检查 troop_loadout 格式是否正确
3. 生成报告和建议修复方案

使用方法:
    python scripts/audit_mission_troop_loadout.py --dry-run  # 仅检查，不修复
    python scripts/audit_mission_troop_loadout.py --fix       # 自动修复
"""
import sys
import django
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
django.setup()

import argparse
from django.db import transaction
from django.utils import timezone
from gameplay.models import MissionRun, PlayerTroop
from battle.models import TroopTemplate


def audit_mission_runs(dry_run=True):
    """
    巡检所有 MissionRun 的 troop_loadout

    Args:
        dry_run: 如果为 True，仅报告问题不修复

    Returns:
        dict: 巡检结果统计
    """
    print("=" * 60)
    print("开始巡检 MissionRun 护院配置...")
    print(f"模式: {'仅检查（不修复）' if dry_run else '自动修复'}")
    print("=" * 60)

    # 获取所有有 troop_loadout 的 run
    runs_with_loadout = MissionRun.objects.exclude(troop_loadout__isnull=True).exclude(troop_loadout={})

    total = runs_with_loadout.count()
    print(f"\n总共 {total} 个任务记录包含护院配置\n")

    issues = {
        "invalid_keys": [],       # 包含不存在的 troop_template.key
        "format_errors": [],      # 格式错误
        "missing_player_troop": [],  # 玩家没有该护院
        "completed_runs": [],     # 已完成的任务（低风险）
        "active_runs": [],        # 进行中的任务（高风险）
    }

    for run in runs_with_loadout:
        loadout = run.troop_loadout or {}

        # 检查格式
        if not isinstance(loadout, dict):
            issues["format_errors"].append({
                "run_id": run.id,
                "manor_id": run.manor_id,
                "error": f"troop_loadout 不是字典类型: {type(loadout)}"
            })
            continue

        if not loadout:
            continue

        # 检查每个 troop_key
        invalid_keys = []
        missing_troops = []

        for troop_key, count in loadout.items():
            # 检查 TroopTemplate 是否存在
            if not TroopTemplate.objects.filter(key=troop_key).exists():
                invalid_keys.append(troop_key)
                continue

            # 检查玩家是否有该护院
            troop_exists = PlayerTroop.objects.filter(
                manor=run.manor,
                troop_template__key=troop_key
            ).exists()

            if not troop_exists:
                missing_troops.append(troop_key)

        # 记录问题
        if invalid_keys:
            issues["invalid_keys"].append({
                "run_id": run.id,
                "manor_id": run.manor_id,
                "mission": run.mission.key if run.mission else "N/A",
                "invalid_keys": invalid_keys,
                "status": run.status,
                "return_at": run.return_at,
            })

        if missing_troops:
            issue = {
                "run_id": run.id,
                "manor_id": run.manor_id,
                "mission": run.mission.key if run.mission else "N/A",
                "missing_troops": missing_troops,
                "status": run.status,
                "return_at": run.return_at,
            }

            # 分类：进行中的任务是高风险
            if run.status == "ACTIVE" and (run.return_at is None or run.return_at > timezone.now()):
                issues["active_runs"].append(issue)
            else:
                issues["completed_runs"].append(issue)

    # 打印报告
    _print_report(issues)

    # 自动修复（如果指定）
    if not dry_run:
        _fix_issues(issues)

    return issues


def _print_report(issues):
    """打印巡检报告"""
    print("\n" + "=" * 60)
    print("巡检结果")
    print("=" * 60)

    # 格式错误
    if issues["format_errors"]:
        print(f"\n❌ 格式错误: {len(issues['format_errors'])} 个")
        for error in issues["format_errors"][:5]:  # 只显示前5个
            print(f"  - Run {error['run_id']}: {error['error']}")
        if len(issues["format_errors"]) > 5:
            print(f"  ... 还有 {len(issues['format_errors']) - 5} 个")

    # 不存在的 troop key
    if issues["invalid_keys"]:
        print(f"\n⚠️  包含不存在的护院类型: {len(issues['invalid_keys'])} 个")
        for issue in issues["invalid_keys"][:5]:
            print(f"  - Run {issue['run_id']} (庄园 {issue['manor_id']}): {issue['invalid_keys']}")
        if len(issues["invalid_keys"]) > 5:
            print(f"  ... 还有 {len(issues['invalid_keys']) - 5} 个")

    # 已完成任务（低风险）
    if issues["completed_runs"]:
        print(f"\n✅ 已完成任务（玩家缺少护院）: {len(issues['completed_runs'])} 个")
        print("   这些任务已完成，风险较低（已归还或已扣除）")
        for issue in issues["completed_runs"][:3]:
            print(f"  - Run {issue['run_id']}: {issue['missing_troops']}")
        if len(issues["completed_runs"]) > 3:
            print(f"  ... 还有 {len(issues['completed_runs']) - 3} 个")

    # 进行中任务（高风险）
    if issues["active_runs"]:
        print(f"\n🔴 进行中任务（玩家缺少护院，高风险）: {len(issues['active_runs'])} 个")
        print("   警告：这些任务结算时可能触发护院复制漏洞！")
        for issue in issues["active_runs"]:
            print(f"  - Run {issue['run_id']} (庄园 {issue['manor_id']})")
            print(f"    缺少护院: {issue['missing_troops']}")
            print(f"    返程时间: {issue['return_at']}")

    # 汇总
    total_issues = (
        len(issues["format_errors"]) +
        len(issues["invalid_keys"]) +
        len(issues["completed_runs"]) +
        len(issues["active_runs"])
    )

    print("\n" + "=" * 60)
    if total_issues == 0:
        print("✨ 未发现任何问题，数据健康！")
    else:
        print(f"⚠️  共发现 {total_issues} 个问题")
        if issues["active_runs"]:
            print(f"   其中 {len(issues['active_runs'])} 个为高风险")
    print("=" * 60)


def _fix_issues(issues):
    """自动修复问题"""
    print("\n" + "=" * 60)
    print("开始自动修复...")
    print("=" * 60)

    fixed = 0

    # 修复高风险任务：清空 troop_loadout
    for issue in issues["active_runs"]:
        try:
            with transaction.atomic():
                run = MissionRun.objects.select_for_update().get(pk=issue["run_id"])
                # 记录原始配置
                original = run.troop_loadout.copy()
                # 清空配置
                run.troop_loadout = {}
                run.save(update_fields=["troop_loadout"])
                fixed += 1
                print(f"✅ Run {run.id}: 已清空 troop_loadout (原始: {original})")
        except Exception as e:
            print(f"❌ Run {issue['run_id']}: 修复失败 - {e}")

    print(f"\n共修复 {fixed} 个高风险任务")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="护院配置数据巡检脚本")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="自动修复问题（默认仅检查）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="仅检查，不修复（默认）"
    )

    args = parser.parse_args()

    # 如果指定了 --fix，则不是 dry-run
    dry_run = not args.fix

    try:
        audit_mission_runs(dry_run=dry_run)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
