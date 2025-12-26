"""
添加酒馆建筑

酒馆：10级满级，满级每小时得1000两银子，增加招募人数10位
"""

from django.db import migrations


def create_tavern(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    # 酒馆：银两产出 + 招募人数加成
    # 10级满级每小时1000两银子
    # base_rate * (1 + rate_growth * (level - 1)) = 1000 at level 10
    # 设 base_rate = 345, rate_growth = 0.211
    # 345 * (1 + 0.211 * 9) = 345 * 2.899 ≈ 1000
    tavern, _ = BuildingType.objects.update_or_create(
        key="tavern",
        defaults={
            "name": "酒馆",
            "description": "江湖人士聚集的场所。提升酒馆等级可增加银两收入，并增加招募候选人数。满级(10级)每小时产银1000两，招募候选人数+10位。",
            "resource_type": "silver",
            "base_rate_per_hour": 345,
            "rate_growth": 0.211,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"wood": 400, "stone": 200, "iron": 50, "silver": 500},
            "cost_growth": 1.35,
            "icon": "tavern",
        },
    )

    # 为所有现有庄园创建酒馆
    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=tavern)


def remove_tavern(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key="tavern").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0047_add_production_buildings"),
    ]

    operations = [
        migrations.RunPython(create_tavern, remove_tavern),
    ]
