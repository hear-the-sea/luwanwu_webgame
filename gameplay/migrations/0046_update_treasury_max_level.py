"""
更新藏宝阁建筑：满级修改为30级，满级容量15000
"""

from django.db import migrations


def update_treasury(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")

    # 更新藏宝阁建筑描述
    BuildingType.objects.filter(key="treasury").update(
        description="用于安全存储珍贵物品的建筑。藏宝阁中的物品不会被抢夺（trade属性为true的物品除外）。初始容量500，每级增加500容量，最高30级（满级15000容量）。"
    )


def revert_treasury(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")

    BuildingType.objects.filter(key="treasury").update(
        description="用于安全存储珍贵物品的建筑。藏宝阁中的物品不会被抢夺（trade属性为true的物品除外）。初始容量500，每级增加100容量，最高10级。"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0045_add_silver_vault_granary"),
    ]

    operations = [
        migrations.RunPython(update_treasury, revert_treasury),
    ]
