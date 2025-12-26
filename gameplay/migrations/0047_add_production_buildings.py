"""
添加畜牧场、冶炼坊、马房建筑，并更新练功场效果

- 畜牧场：10级满级，满级家畜制造速度提升50%
- 冶炼坊：10级满级，满级铁矿等物资制造速度提升50%
- 马房：10级满级，满级马制造速度提升50%
- 练功场：10级满级，满级护院训练速度提升30%（原每级3%，现调整为每级约3.33%）
"""

from django.db import migrations


def create_buildings(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    # 畜牧场：家畜制造速度提升
    # 10级满级提升50%，每级约5.56%
    ranch, _ = BuildingType.objects.update_or_create(
        key="ranch",
        defaults={
            "name": "畜牧场",
            "description": "饲养家畜的场所。提升畜牧场等级可加快家畜制造速度。满级(10级)家畜制造速度提升50%。",
            "resource_type": "grain",
            "base_rate_per_hour": 0,
            "rate_growth": 0,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"wood": 300, "stone": 150, "iron": 50, "silver": 300},
            "cost_growth": 1.35,
            "icon": "ranch",
        },
    )

    # 冶炼坊：铁矿等物资制造速度提升
    # 10级满级提升50%，每级约5.56%
    smithy, _ = BuildingType.objects.update_or_create(
        key="smithy",
        defaults={
            "name": "冶炼坊",
            "description": "冶炼金属的工坊。提升冶炼坊等级可加快铁矿等物资的制造速度。满级(10级)物资制造速度提升50%。",
            "resource_type": "iron",
            "base_rate_per_hour": 0,
            "rate_growth": 0,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"wood": 200, "stone": 300, "iron": 100, "silver": 400},
            "cost_growth": 1.35,
            "icon": "smithy",
        },
    )

    # 马房：马制造速度提升
    # 10级满级提升50%，每级约5.56%
    stable, _ = BuildingType.objects.update_or_create(
        key="stable",
        defaults={
            "name": "马房",
            "description": "饲养马匹的建筑。提升马房等级可加快马匹的制造速度。满级(10级)马制造速度提升50%。",
            "resource_type": "grain",
            "base_rate_per_hour": 0,
            "rate_growth": 0,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"wood": 350, "stone": 200, "iron": 80, "silver": 350},
            "cost_growth": 1.35,
            "icon": "stable",
        },
    )

    # 更新练功场描述：10级满级提升30%
    BuildingType.objects.filter(key="lianggongchang").update(
        description="可将家丁训练为护院，等级越高训练速度越快。满级(10级)护院训练速度提升30%。"
    )

    # 为所有现有庄园创建新建筑
    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=ranch)
        Building.objects.get_or_create(manor=manor, building_type=smithy)
        Building.objects.get_or_create(manor=manor, building_type=stable)


def remove_buildings(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key__in=["ranch", "smithy", "stable"]).delete()

    # 恢复练功场描述
    BuildingType.objects.filter(key="lianggongchang").update(
        description="可将家丁训练为护院，等级越高训练速度越快。每提升一级训练护院的速度增加3%。"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0046_update_treasury_max_level"),
    ]

    operations = [
        migrations.RunPython(create_buildings, remove_buildings),
    ]
