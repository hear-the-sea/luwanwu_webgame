"""
修复护院归还问题的数据脚本

用于修复因并发冲突导致护院未正确归还的历史数据
"""
import os
import sys
import django
import argparse
from pathlib import Path

# 设置 Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import F  # noqa: E402
from django.utils import timezone  # noqa: E402

from gameplay.models import MissionRun, PlayerTroop  # noqa: E402


def _compute_troops_lost(casualties: list[dict], loadout: dict) -> dict[str, int]:
    troops_lost: dict[str, int] = {}
    for entry in casualties:
        key = entry.get('key')
        if key not in loadout:
            continue
        try:
            lost = int(entry.get('lost', 0) or 0)
        except (TypeError, ValueError):
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost
    return troops_lost


def _compute_target_troops(loadout: dict, troops_lost: dict[str, int]) -> dict[str, int]:
    target_troops: dict[str, int] = {}
    for troop_key, original_count in loadout.items():
        if original_count == 0:
            continue

        lost = troops_lost.get(troop_key, 0)
        if lost > original_count:
            print(f"  ⚠️  {troop_key}: 损失({lost}) > 出征({original_count}), 已修正")
            lost = original_count

        surviving = max(0, original_count - lost)
        if surviving > 0:
            target_troops[troop_key] = surviving
            print(f"  {troop_key}: 出征 {original_count}, 损失 {lost}, 应归还 {surviving}")
    return target_troops


def _resolve_target_troops(run) -> dict[str, int]:
    loadout = run.troop_loadout or {}

    print("\n出征配置:")
    for key, count in loadout.items():
        if count > 0:
            print(f"  {key}: {count}")

    report = run.battle_report
    if not report:
        print("\n⚠️  无战报，将全额归还")
        return loadout

    print("\n有战报，将按损失归还")
    losses = report.losses or {}
    casualties = (losses.get('attacker', {}) or {}).get('casualties', []) or []
    troops_lost = _compute_troops_lost(casualties, loadout)
    return _compute_target_troops(loadout, troops_lost)


def _apply_troop_return(manor, target_troops: dict[str, int]) -> None:
    print("\n执行归还:")
    print("-" * 60)

    with transaction.atomic():
        existing = {
            pt.troop_template.key: pt
            for pt in PlayerTroop.objects.select_for_update()
            .filter(manor=manor, troop_template__key__in=target_troops.keys())
            .select_related('troop_template')
        }

        now = timezone.now()
        for key, count in target_troops.items():
            if key in existing:
                old_count = existing[key].count
                PlayerTroop.objects.filter(pk=existing[key].pk).update(count=F("count") + count, updated_at=now)
                existing[key].refresh_from_db()
                new_count = existing[key].count
                print(f"  ✅ {key}: {old_count} + {count} = {new_count}")
            else:
                print(f"  ⚠️  {key}: 需要创建新记录 (count={count})")


def _print_run_meta(run) -> bool:
    print(f"\n任务状态: {run.status}")
    print(f"完成时间: {run.completed_at}")
    print(f"是否防守任务: {run.mission.is_defense}")
    print(f"是否撤退: {run.is_retreating}")

    if run.status != MissionRun.Status.COMPLETED:
        print("\n❌ 任务未完成，跳过修复")
        return False

    if run.mission.is_defense:
        print("\n❌ 防守任务不涉及护院归还，跳过")
        return False

    return True


def fix_mission_troop_return(run_id: int):
    """
    修复指定任务的护院归还问题

    Args:
        run_id: MissionRun ID
    """
    print("=" * 60)
    print(f"修复任务 {run_id} 的护院归还")
    print("=" * 60)

    run = MissionRun.objects.select_related('manor', 'battle_report', 'mission').get(pk=run_id)
    if not _print_run_meta(run):
        return

    target_troops = _resolve_target_troops(run)
    if not target_troops:
        print("\n✅ 没有需要归还的护院")
        return

    _apply_troop_return(run.manor, target_troops)

    print("\n" + "=" * 60)
    print("✅ 修复完成")
    print("=" * 60)


def _dry_run_preview(run_id: int) -> None:
    run = MissionRun.objects.select_related('manor', 'battle_report', 'mission').get(pk=run_id)
    loadout = run.troop_loadout or {}

    print("\n出征配置:")
    for key, count in loadout.items():
        if count > 0:
            print(f"  {key}: {count}")

    report = run.battle_report
    if not report:
        print("\n应归还:")
        for key, count in loadout.items():
            if count > 0:
                print(f"  {key}: {count}")
        return

    casualties = ((report.losses or {}).get('attacker', {}) or {}).get('casualties', []) or []
    troops_lost = _compute_troops_lost(casualties, loadout)

    print("\n应归还:")
    for troop_key, original_count in loadout.items():
        if original_count == 0:
            continue
        surviving = max(0, original_count - troops_lost.get(troop_key, 0))
        if surviving > 0:
            print(f"  {troop_key}: {surviving}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复护院归还问题")
    parser.add_argument("run_id", type=int, help="MissionRun ID")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不实际修改")
    args = parser.parse_args()

    if args.dry_run:
        print("=" * 60)
        print("⚠️  DRY RUN 模式：不会实际修改数据")
        print("=" * 60)

        try:
            _dry_run_preview(args.run_id)
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            import traceback

            traceback.print_exc()
    else:
        try:
            fix_mission_troop_return(args.run_id)
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)
