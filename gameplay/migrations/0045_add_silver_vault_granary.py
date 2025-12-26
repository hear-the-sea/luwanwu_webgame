"""
添加银库和粮仓建筑

银库：20级满级，满级银两上限1050万
粮仓：20级满级，满级粮食上限1050万
"""

from django.db import migrations


def create_buildings(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    # 银库建筑
    # 1级: 20,000  20级: 10,500,000
    # 增长系数: (10500000/20000)^(1/19) ≈ 1.417
    # 为了容量计算方便，这里不使用产出字段
    silver_vault, _ = BuildingType.objects.update_or_create(
        key="silver_vault",
        defaults={
            "name": "银库",
            "description": "存放银两的库房。提升银库等级可增加银两存储上限。满级(20级)可存储1050万两银子。",
            "resource_type": "silver",
            "base_rate_per_hour": 0,  # 不产出资源
            "rate_growth": 0,
            "base_upgrade_time": 300,
            "time_growth": 1.20,
            "base_cost": {"wood": 200, "stone": 300, "iron": 100, "silver": 500},
            "cost_growth": 1.35,
            "icon": "silver_vault",
        },
    )

    # 粮仓建筑
    granary, _ = BuildingType.objects.update_or_create(
        key="granary",
        defaults={
            "name": "粮仓",
            "description": "存放粮食的仓库。提升粮仓等级可增加粮食存储上限。满级(20级)可存储1050万石粮食。",
            "resource_type": "grain",
            "base_rate_per_hour": 0,  # 不产出资源
            "rate_growth": 0,
            "base_upgrade_time": 300,
            "time_growth": 1.20,
            "base_cost": {"wood": 300, "stone": 200, "iron": 50, "silver": 400},
            "cost_growth": 1.35,
            "icon": "granary",
        },
    )

    # 为所有现有庄园创建建筑
    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=silver_vault)
        Building.objects.get_or_create(manor=manor, building_type=granary)


def remove_buildings(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key__in=["silver_vault", "granary"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0044_add_prestige_system"),
    ]

    operations = [
        migrations.RunPython(create_buildings, remove_buildings),
    ]
