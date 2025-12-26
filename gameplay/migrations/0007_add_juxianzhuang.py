from django.db import migrations


def add_recruit_building(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Manor = apps.get_model("gameplay", "Manor")
    Building = apps.get_model("gameplay", "Building")

    hall, _ = BuildingType.objects.update_or_create(
        key="juxianzhuang",
        defaults={
            "name": "聚贤庄",
            "description": "门客招募场所，等级越高可容纳的门客上限越高。",
            "resource_type": "silver",
            "base_rate_per_hour": 0,
            "rate_growth": 0.0,
            "base_upgrade_time": 240,
            "time_growth": 1.25,
            "base_cost": {"wood": 200, "stone": 150, "iron": 120},
            "cost_growth": 1.35,
            "icon": "guest",
        },
    )

    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=hall)


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0006_alter_buildingtype_resource_type_and_more"),
    ]

    operations = [
        migrations.RunPython(add_recruit_building, migrations.RunPython.noop),
    ]
