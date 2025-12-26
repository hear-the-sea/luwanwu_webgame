"""
添加铁匠铺建筑

铁匠铺用于锻造装备，10级满级可提升50%锻造速度。
"""

from django.db import migrations


def create_forge_building(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    # 铁匠铺：装备锻造速度提升
    # 10级满级提升50%，每级约5%
    forge, _ = BuildingType.objects.update_or_create(
        key="forge",
        defaults={
            "name": "铁匠铺",
            "description": "锻造装备的工坊。提升铁匠铺等级可加快装备锻造速度。满级(10级)锻造速度提升50%。",
            "resource_type": "silver",
            "base_rate_per_hour": 0,
            "rate_growth": 0,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"grain": 500, "silver": 500},
            "cost_growth": 1.35,
            "icon": "forge",
        },
    )

    # 为所有现有庄园创建铁匠铺建筑
    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=forge)


def remove_forge_building(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key="forge").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0058_update_building_resource_types"),
    ]

    operations = [
        migrations.RunPython(create_forge_building, remove_forge_building),
    ]
