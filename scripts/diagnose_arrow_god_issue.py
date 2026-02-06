"""
诊断护院归还问题

用于诊断 arrow_god 护院归还失败的问题
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

from battle.models import TroopTemplate  # noqa: E402
from django.db import transaction  # noqa: E402
from gameplay.models import MissionRun, PlayerTroop  # noqa: E402


def diagnose_arrow_god_return(run_id: int):
    """诊断 arrow_god 护院归还问题"""
    print("=" * 60)
    print(f"诊断任务 {run_id} 的 arrow_god 归还问题")
    print("=" * 60)

    run = MissionRun.objects.select_related('manor', 'battle_report', 'mission').get(pk=run_id)
    manor = run.manor
    report = run.battle_report

    # 1. 检查出征配置
    loadout = run.troop_loadout or {}
    print("\n1. 出征配置:")
    arrow_deployed = loadout.get('arrow_god', 0)
    print(f"   arrow_god: {arrow_deployed}")

    # 2. 检查战报损失
    print("\n2. 战报损失:")
    losses = report.losses or {}
    attacker_losses = losses.get('attacker', {})
    casualties = attacker_losses.get('casualties', [])

    arrow_lost = 0
    for entry in casualties:
        if entry.get('key') == 'arrow_god':
            lost = entry.get('lost', 0)
            arrow_lost += lost
            print(f"   arrow_god: 损失 {lost}")

    print(f"   累计损失: {arrow_lost}")
    print(f"   应该剩余: {arrow_deployed - arrow_lost}")

    # 3. 检查当前库存
    print("\n3. 当前库存:")
    arrow_troop = PlayerTroop.objects.filter(
        manor=manor,
        troop_template__key='arrow_god'
    ).first()

    if arrow_troop:
        print(f"   arrow_god: {arrow_troop.count}")
        print(f"   updated_at: {arrow_troop.updated_at}")
        print(f"   战报完成时间: {report.completed_at}")

        if arrow_troop.updated_at > report.completed_at:
            print("   ✅ 护院在战斗后被更新过")
        else:
            print("   ❌ 护院在战斗后没有被更新")

        # 4. 检查是否有多次更新
        print("\n4. 检查是否有多次出征/归还:")
        recent_runs = MissionRun.objects.filter(
            manor=manor,
            troop_loadout__arrow_god__gt=0
        ).order_by('-started_at')[:5]

        print("   最近的 arrow_god 出征记录:")
        for r in recent_runs:
            arrow_count = r.troop_loadout.get('arrow_god', 0)
            print(f"     任务 {r.id}: 出征 {arrow_count}, 时间 {r.started_at}, 状态 {r.status}")

    else:
        print("   ❌ 没有 arrow_god 的 PlayerTroop 记录")

    # 5. 模拟完整的归还流程
    print("\n5. 模拟完整的归还流程:")

    # 计算 surviving_troops
    troops_lost = {}
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

    surviving_troops = {}
    for troop_key, original_count in loadout.items():
        if original_count == 0:
            continue
        lost = troops_lost.get(troop_key, 0)
        surviving = max(0, original_count - lost)
        if surviving > 0:
            surviving_troops[troop_key] = surviving

    print(f"   surviving_troops: {surviving_troops}")

    # 检查 _add_troops_batch 的逻辑
    troops_to_add = surviving_troops
    print("\n6. 模拟 _add_troops_batch:")

    with transaction.atomic():
        # 预加载模板
        templates = {t.key: t for t in TroopTemplate.objects.filter(key__in=troops_to_add.keys())}
        print(f"   模板数量: {len(templates)}")

        # 预加载现有护院
        existing = {
            pt.troop_template.key: pt
            for pt in PlayerTroop.objects.select_for_update()
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
                pt = existing[key]
                original = pt.count
                pt.count += count
                print(f"   {key}: 原始 {original}, 添加 {count}, 结果 {pt.count}")
                to_update.append(pt)
            else:
                print(f"   {key}: 不在 existing，需要创建")
                to_create.append(PlayerTroop(manor=manor, troop_template=template, count=count))

        print(f"\n   to_update 数量: {len(to_update)}")
        print(f"   to_create 数量: {len(to_create)}")

        if to_update:
            print("   to_update 详情:")
            for pt in to_update:
                print(f"     {pt.troop_template.key}: count={pt.count}")

    # 7. 检查是否有异常被吞掉
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
