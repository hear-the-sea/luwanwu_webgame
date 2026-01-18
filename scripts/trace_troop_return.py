"""
追踪护院归还逻辑执行情况

用于调试护院归还问题，显示详细的执行流程
"""
import os
import sys
import django
from pathlib import Path

# 设置 Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
django.setup()

from gameplay.models import MissionRun, PlayerTroop
from gameplay.services.troops import _return_surviving_troops_batch, _add_troops_batch
from battle.models import TroopTemplate
from django.db import transaction
from django.utils import timezone


def trace_troop_return(run_id: int):
    """追踪护院归还逻辑"""
    print("=" * 80)
    print(f"追踪任务 {run_id} 的护院归还逻辑")
    print("=" * 80)

    run = MissionRun.objects.select_related('manor', 'battle_report', 'mission').get(pk=run_id)
    manor = run.manor
    report = run.battle_report

    print(f"\n1. 基本信息:")
    print(f"   状态: {run.status}")
    print(f"   完成: {run.completed_at}")
    print(f"   是否防守: {run.mission.is_defense}")
    print(f"   是否撤退: {run.is_retreating}")

    # 显示出征配置
    loadout = run.troop_loadout or {}
    print(f"\n2. 出征配置 (run.troop_loadout):")
    for key, count in loadout.items():
        if count > 0:
            print(f"   {key}: {count}")
        else:
            print(f"   {key}: {count} (为0)")

    # 检查战报
    if not report:
        print(f"\n❌ 无战报，无法追踪")
        return

    # 解析战报损失
    print(f"\n3. 战报损失:")
    losses = report.losses or {}
    attacker_losses = losses.get('attacker', {}) or {}
    casualties = attacker_losses.get('casualties", [])

    if not casualties:
        print(f"   (无伤亡记录)")
    else:
        # 只显示在 loadout 中的护院
        for entry in casualties:
            key = entry.get('key')
            if key in loadout and loadout[key] > 0:
                lost = entry.get('lost', 0)
                print(f"   {key}: 损失 {lost}")

    # 模拟计算 surviving_troops
    print(f"\n4. 计算 surviving_troops:")
    troops_lost = {}
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

    surviving_troops = {}
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

    print(f"\n5. surviving_troops 结果: {surviving_troops}")

    if not surviving_troops:
        print(f"\n❌ surviving_troops 为空，不会调用 _add_troops_batch")
        print(f"   这就是问题所在！")
        return

    # 检查 _add_troops_batch 执行前的库存
    print(f"\n6. 执行归还前的库存:")
    for key in surviving_troops.keys():
        pt = PlayerTroop.objects.filter(
            manor=manor,
            troop_template__key=key
        ).first()
        if pt:
            print(f"   {key}: {pt.count}")
        else:
            print(f"   {key}: (不存在)")

    # 执行归还（不实际修改数据库，只模拟）
    print(f"\n7. 模拟 _add_troops_batch 逻辑:")

    troops_to_add = surviving_troops

    # 预加载模板
    templates = {t.key: t for t in TroopTemplate.objects.filter(key__in=troops_to_add.keys())}
    print(f"   模板数量: {len(templates)}")

    if not templates:
        print(f"   ❌ 模板为空，无法归还")
        return

    # 预加载现有护院
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

    print(f"\n8. 结论:")
    print(f"   surviving_troops 不为空")
    print(f"   应该会调用 _add_troops_batch")
    print(f"   如果实际库存没有增加，说明:")
    print(f"   1. 事务被回滚")
    print(f"   2. _add_troops_batch 内部出错")
    print(f"   3. 原子更新失败")


if __name__ == "__main__":
    import argparse
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
