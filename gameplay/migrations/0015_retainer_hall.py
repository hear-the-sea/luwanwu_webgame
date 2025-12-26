from django.db import migrations, models


def add_retainer_hall(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    hall, _ = BuildingType.objects.update_or_create(
        key="jiadingfang",
        defaults={
            "name": "家丁房",
            "description": "安置家丁的营舍，等级越高可容纳的家丁越多。",
            "resource_type": "grain",
            "base_rate_per_hour": 0,
            "rate_growth": 0.0,
            "base_upgrade_time": 300,
            "time_growth": 1.2,
            "base_cost": {"wood": 150, "stone": 150, "iron": 120},
            "cost_growth": 1.3,
            "icon": "retainer",
        },
    )

    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=hall)


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0014_message_is_read"),
    ]

    operations = [
        migrations.AddField(
            model_name="manor",
            name="retainer_count",
            field=models.PositiveIntegerField(default=0, verbose_name="家丁"),
        ),
        migrations.RunPython(add_retainer_hall, migrations.RunPython.noop),
    ]
