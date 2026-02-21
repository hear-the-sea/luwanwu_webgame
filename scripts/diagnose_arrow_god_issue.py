"""
诊断护院归还问题

用于诊断 arrow_god 护院归还失败的问题
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

from django.db import transaction  # noqa: E402

from battle.models import TroopTemplate  # noqa: E402
from gameplay.models import MissionRun, PlayerTroop  # noqa: E402


def _compute_troops_lost(casualties: list[dict], loadout: dict) -> dict[str, int]:
    troops_lost: dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key")
        if key not in loadout:
            continue
        try:
            lost = int(entry.get("lost", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost
    return troops_lost


def _compute_surviving_troops(loadout: dict, troops_lost: dict[str, int]) -> dict[str, int]:
    surviving_troops: dict[str, int] = {}
    for troop_key, original_count in loadout.items():
        if original_count == 0:
            continue
        lost = troops_lost.get(troop_key, 0)
        surviving = max(0, original_count - lost)
        if surviving > 0:
            surviving_troops[troop_key] = surviving
    return surviving_troops


def _print_recent_runs(manor) -> None:
    recent_runs = MissionRun.objects.filter(manor=manor, troop_loadout__arrow_god__gt=0).order_by("-started_at")[:5]
    print("   最近的 arrow_god 出征记录:")
    for recent_run in recent_runs:
        arrow_count = recent_run.troop_loadout.get("arrow_god", 0)
        print(f"     任务 {recent_run.id}: 出征 {arrow_count}, 时间 {recent_run.started_at}, 状态 {recent_run.status}")


def _simulate_add_troops_batch(manor, troops_to_add: dict[str, int]) -> None:
    print("\n6. 模拟 _add_troops_batch:")

    with transaction.atomic():
        templates = {template.key: template for template in TroopTemplate.objects.filter(key__in=troops_to_add.keys())}
        print(f"   模板数量: {len(templates)}")

        existing = {
            player_troop.troop_template.key: player_troop
            for player_troop in PlayerTroop.objects.select_for_update()
            .filter(manor=manor, troop_template__key__in=troops_to_add.keys())
            .select_related("troop_template")
        }
        print(f"   existing keys: {list(existing.keys())}")

        to_update = []
        to_create = []
        for key, count in troops_to_add.items():
            template = templates.get(key)
            if not template:
                print(f"   ❌ {key}: 模板不存在，跳过")
                continue

            if key in existing:
                player_troop = existing[key]
                original = player_troop.count
                player_troop.count += count
                print(f"   {key}: 原始 {original}, 添加 {count}, 结果 {player_troop.count}")
                to_update.append(player_troop)
            else:
                print(f"   {key}: 不在 existing，需要创建")
                to_create.append(PlayerTroop(manor=manor, troop_template=template, count=count))

        print(f"\n   to_update 数量: {len(to_update)}")
        print(f"   to_create 数量: {len(to_create)}")
        if to_update:
            print("   to_update 详情:")
            for player_troop in to_update:
                print(f"     {player_troop.troop_template.key}: count={player_troop.count}")


def diagnose_arrow_god_return(run_id: int):
    """诊断 arrow_god 护院归还问题"""
    print("=" * 60)
    print(f"诊断任务 {run_id} 的 arrow_god 归还问题")
    print("=" * 60)

    run = MissionRun.objects.select_related("manor", "battle_report", "mission").get(pk=run_id)
    manor = run.manor
    report = run.battle_report

    loadout = run.troop_loadout or {}
    print("\n1. 出征配置:")
    arrow_deployed = loadout.get("arrow_god", 0)
    print(f"   arrow_god: {arrow_deployed}")

    print("\n2. 战报损失:")
    losses = report.losses or {}
    casualties = (losses.get("attacker", {}) or {}).get("casualties", [])

    arrow_lost = 0
    for entry in casualties:
        if entry.get("key") != "arrow_god":
            continue
        lost = entry.get("lost", 0)
        arrow_lost += lost
        print(f"   arrow_god: 损失 {lost}")

    print(f"   累计损失: {arrow_lost}")
    print(f"   应该剩余: {arrow_deployed - arrow_lost}")

    print("\n3. 当前库存:")
    arrow_troop = PlayerTroop.objects.filter(manor=manor, troop_template__key="arrow_god").first()
    if not arrow_troop:
        print("   ❌ 没有 arrow_god 的 PlayerTroop 记录")
    else:
        print(f"   arrow_god: {arrow_troop.count}")
        print(f"   updated_at: {arrow_troop.updated_at}")
        print(f"   战报完成时间: {report.completed_at}")
        if arrow_troop.updated_at > report.completed_at:
            print("   ✅ 护院在战斗后被更新过")
        else:
            print("   ❌ 护院在战斗后没有被更新")

        print("\n4. 检查是否有多次出征/归还:")
        _print_recent_runs(manor)

    print("\n5. 模拟完整的归还流程:")
    troops_lost = _compute_troops_lost(casualties, loadout)
    surviving_troops = _compute_surviving_troops(loadout, troops_lost)
    print(f"   surviving_troops: {surviving_troops}")

    _simulate_add_troops_batch(manor, surviving_troops)

    print("\n7. 检查可能的异常:")
    print("   建议：查看应用日志，搜索 '归还护院' 或 '批量更新护院'")
    print("   检查是否有异常或错误信息")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="诊断护院归还问题")
    parser.add_argument("run_id", type=int, help="MissionRun ID")
    args = parser.parse_args()

    try:
        diagnose_arrow_god_return(args.run_id)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
