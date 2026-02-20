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

import argparse  # noqa: E402

from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from battle.models import TroopTemplate  # noqa: E402
from gameplay.models import MissionRun, PlayerTroop  # noqa: E402


def _empty_issues() -> dict:
    return {
        "invalid_keys": [],
        "format_errors": [],
        "missing_player_troop": [],
        "completed_runs": [],
        "active_runs": [],
    }


def _is_high_risk_active_run(run: MissionRun) -> bool:
    return run.status == "ACTIVE" and (run.return_at is None or run.return_at > timezone.now())


def _build_run_issue(run: MissionRun, missing_troops: list[str]) -> dict:
    return {
        "run_id": run.id,
        "manor_id": run.manor_id,
        "mission": run.mission.key if run.mission else "N/A",
        "missing_troops": missing_troops,
        "status": run.status,
        "return_at": run.return_at,
    }


def _check_run_loadout(run: MissionRun, loadout: dict) -> tuple[list[str], list[str]]:
    invalid_keys: list[str] = []
    missing_troops: list[str] = []

    for troop_key in loadout:
        if not TroopTemplate.objects.filter(key=troop_key).exists():
            invalid_keys.append(troop_key)
            continue

        troop_exists = PlayerTroop.objects.filter(manor=run.manor, troop_template__key=troop_key).exists()
        if not troop_exists:
            missing_troops.append(troop_key)

    return invalid_keys, missing_troops


def _append_run_issues(issues: dict, run: MissionRun, loadout) -> None:
    if not isinstance(loadout, dict):
        issues["format_errors"].append(
            {
                "run_id": run.id,
                "manor_id": run.manor_id,
                "error": f"troop_loadout 不是字典类型: {type(loadout)}",
            }
        )
        return

    if not loadout:
        return

    invalid_keys, missing_troops = _check_run_loadout(run, loadout)

    if invalid_keys:
        issues["invalid_keys"].append(
            {
                "run_id": run.id,
                "manor_id": run.manor_id,
                "mission": run.mission.key if run.mission else "N/A",
                "invalid_keys": invalid_keys,
                "status": run.status,
                "return_at": run.return_at,
            }
        )

    if not missing_troops:
        return

    issue = _build_run_issue(run, missing_troops)
    if _is_high_risk_active_run(run):
        issues["active_runs"].append(issue)
    else:
        issues["completed_runs"].append(issue)


def _print_format_errors(issues: dict) -> None:
    if not issues["format_errors"]:
        return

    print(f"\n❌ 格式错误: {len(issues['format_errors'])} 个")
    for error in issues["format_errors"][:5]:
        print(f"  - Run {error['run_id']}: {error['error']}")
    if len(issues["format_errors"]) > 5:
        print(f"  ... 还有 {len(issues['format_errors']) - 5} 个")


def _print_invalid_keys(issues: dict) -> None:
    if not issues["invalid_keys"]:
        return

    print(f"\n⚠️  包含不存在的护院类型: {len(issues['invalid_keys'])} 个")
    for issue in issues["invalid_keys"][:5]:
        print(f"  - Run {issue['run_id']} (庄园 {issue['manor_id']}): {issue['invalid_keys']}")
    if len(issues["invalid_keys"]) > 5:
        print(f"  ... 还有 {len(issues['invalid_keys']) - 5} 个")


def _print_completed_runs(issues: dict) -> None:
    if not issues["completed_runs"]:
        return

    print(f"\n✅ 已完成任务（玩家缺少护院）: {len(issues['completed_runs'])} 个")
    print("   这些任务已完成，风险较低（已归还或已扣除）")
    for issue in issues["completed_runs"][:3]:
        print(f"  - Run {issue['run_id']}: {issue['missing_troops']}")
    if len(issues["completed_runs"]) > 3:
        print(f"  ... 还有 {len(issues['completed_runs']) - 3} 个")


def _print_active_runs(issues: dict) -> None:
    if not issues["active_runs"]:
        return

    print(f"\n🔴 进行中任务（玩家缺少护院，高风险）: {len(issues['active_runs'])} 个")
    print("   警告：这些任务结算时可能触发护院复制漏洞！")
    for issue in issues["active_runs"]:
        print(f"  - Run {issue['run_id']} (庄园 {issue['manor_id']})")
        print(f"    缺少护院: {issue['missing_troops']}")
        print(f"    返程时间: {issue['return_at']}")


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

    runs_with_loadout = MissionRun.objects.exclude(troop_loadout__isnull=True).exclude(troop_loadout={})
    total = runs_with_loadout.count()
    print(f"\n总共 {total} 个任务记录包含护院配置\n")

    issues = _empty_issues()
    for run in runs_with_loadout:
        _append_run_issues(issues, run, run.troop_loadout or {})

    _print_report(issues)

    if not dry_run:
        _fix_issues(issues)

    return issues


def _print_report(issues):
    """打印巡检报告"""
    print("\n" + "=" * 60)
    print("巡检结果")
    print("=" * 60)

    _print_format_errors(issues)
    _print_invalid_keys(issues)
    _print_completed_runs(issues)
    _print_active_runs(issues)

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

    for issue in issues["active_runs"]:
        try:
            with transaction.atomic():
                run = MissionRun.objects.select_for_update().get(pk=issue["run_id"])
                original = run.troop_loadout.copy()
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

    dry_run = not args.fix

    try:
        audit_mission_runs(dry_run=dry_run)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
