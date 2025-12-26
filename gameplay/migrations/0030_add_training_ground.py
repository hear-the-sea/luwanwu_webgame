from django.db import migrations


def add_training_ground(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    training_ground, _ = BuildingType.objects.update_or_create(
        key="lianggongchang",
        defaults={
            "name": "练功场",
            "description": "可将家丁训练为护院，等级越高训练速度越快。每提升一级训练护院的速度增加3%。",
            "resource_type": "grain",
            "base_rate_per_hour": 0,
            "rate_growth": 0.0,
            "base_upgrade_time": 300,
            "time_growth": 1.2,
            "base_cost": {"wood": 200, "stone": 200, "iron": 150},
            "cost_growth": 1.3,
            "icon": "training",
        },
    )

    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=training_ground)


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0029_change_building_key_to_jiadingfang"),
    ]

    operations = [
        migrations.RunPython(add_training_ground, migrations.RunPython.noop),
    ]
