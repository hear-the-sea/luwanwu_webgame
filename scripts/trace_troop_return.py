"""
追踪护院归还逻辑执行情况

用于调试护院归还问题，显示详细的执行流程
"""

import argparse
import os
import sys
from pathlib import Path

import django

# 设置 Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
django.setup()

from battle.models import TroopTemplate  # noqa: E402
from gameplay.models import MissionRun, PlayerTroop  # noqa: E402


def _print_run_basics(run) -> None:
    print("\n1. 基本信息:")
    print(f"   状态: {run.status}")
    print(f"   完成: {run.completed_at}")
    print(f"   是否防守: {run.mission.is_defense}")
    print(f"   是否撤退: {run.is_retreating}")


def _print_loadout(loadout: dict) -> None:
    print("\n2. 出征配置 (run.troop_loadout):")
    for key, count in loadout.items():
        if count > 0:
            print(f"   {key}: {count}")
        else:
            print(f"   {key}: {count} (为0)")


def _print_casualties(casualties: list[dict], loadout: dict) -> None:
    print("\n3. 战报损失:")
    if not casualties:
        print("   (无伤亡记录)")
        return

    for entry in casualties:
        key = entry.get("key")
        if key in loadout and loadout[key] > 0:
            lost = entry.get("lost", 0)
            print(f"   {key}: 损失 {lost}")


def _compute_surviving_troops(loadout: dict, casualties: list[dict]) -> dict[str, int]:
    print("\n4. 计算 surviving_troops:")
    troops_lost: dict[str, int] = {}

    for entry in casualties:
        key = entry.get("key")
        if key not in loadout:
            print(f"   跳过 {key} (不在 loadout 中)")
            continue
        try:
            lost = int(entry.get("lost", 0) or 0)
        except (TypeError, ValueError):
            print(f"   跳过 {key} (损失数据无效)")
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost

    surviving_troops: dict[str, int] = {}
    for troop_key, original_count in loadout.items():
        if original_count == 0:
            continue
        lost = troops_lost.get(troop_key, 0)
        if lost > original_count:
            print(f"   ⚠️  {troop_key}: 损失({lost}) > 出征({original_count}), 修正为 {original_count}")
            lost = original_count
        surviving = max(0, original_count - lost)
        print(f"   {troop_key}: 出征 {original_count}, 损失 {lost}, 存活 {surviving}")
        if surviving > 0:
            surviving_troops[troop_key] = surviving

    return surviving_troops


def _print_inventory_before_return(manor, surviving_troops: dict[str, int]) -> None:
    print("\n6. 执行归还前的库存:")
    for key in surviving_troops.keys():
        pt = PlayerTroop.objects.filter(manor=manor, troop_template__key=key).first()
        if pt:
            print(f"   {key}: {pt.count}")
        else:
            print(f"   {key}: (不存在)")


def _simulate_add_troops_batch(manor, troops_to_add: dict[str, int]) -> bool:
    print("\n7. 模拟 _add_troops_batch 逻辑:")

    templates = {template.key: template for template in TroopTemplate.objects.filter(key__in=troops_to_add.keys())}
    print(f"   模板数量: {len(templates)}")
    if not templates:
        print("   ❌ 模板为空，无法归还")
        return False

    existing = {
        pt.troop_template.key: pt
        for pt in PlayerTroop.objects.select_for_update()
        .filter(manor=manor, troop_template__key__in=troops_to_add.keys())
        .select_related("troop_template")
    }
    print(f"   existing keys: {list(existing.keys())}")

    to_create = []
    for key, count in troops_to_add.items():
        template = templates.get(key)
        if not template:
            print(f"   ❌ {key}: 模板不存在")
            continue

        if key in existing:
            pt = existing[key]
            print(f"   {key}: 在 existing 中，当前 count={pt.count}")
            print(f"       准备原子更新: {pt.count} + {count} = {pt.count + count}")
        else:
            print(f"   {key}: 不在 existing 中，需要创建")
            to_create.append(f"{key}: {count}")

    if to_create:
        print(f"   需要创建: {to_create}")

    return True


def trace_troop_return(run_id: int):
    """追踪护院归还逻辑"""
    print("=" * 80)
    print(f"追踪任务 {run_id} 的护院归还逻辑")
    print("=" * 80)

    run = MissionRun.objects.select_related("manor", "battle_report", "mission").get(pk=run_id)
    manor = run.manor
    report = run.battle_report

    _print_run_basics(run)

    loadout = run.troop_loadout or {}
    _print_loadout(loadout)

    if not report:
        print("\n❌ 无战报，无法追踪")
        return

    casualties = ((report.losses or {}).get("attacker", {}) or {}).get("casualties", [])
    _print_casualties(casualties, loadout)

    surviving_troops = _compute_surviving_troops(loadout, casualties)
    print(f"\n5. surviving_troops 结果: {surviving_troops}")

    if not surviving_troops:
        print("\n❌ surviving_troops 为空，不会调用 _add_troops_batch")
        print("   这就是问题所在！")
        return

    _print_inventory_before_return(manor, surviving_troops)
    if not _simulate_add_troops_batch(manor, surviving_troops):
        return

    print("\n8. 结论:")
    print("   surviving_troops 不为空")
    print("   应该会调用 _add_troops_batch")
    print("   如果实际库存没有增加，说明:")
    print("   1. 事务被回滚")
    print("   2. _add_troops_batch 内部出错")
    print("   3. 原子更新失败")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="追踪护院归还逻辑")
    parser.add_argument("run_id", type=int, help="MissionRun ID")
    args = parser.parse_args()

    try:
        trace_troop_return(args.run_id)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
