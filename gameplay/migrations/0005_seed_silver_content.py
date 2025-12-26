from django.db import migrations


def add_tax_office(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    TaskTemplate = apps.get_model("gameplay", "TaskTemplate")
    Manor = apps.get_model("gameplay", "Manor")
    Building = apps.get_model("gameplay", "Building")

    tax_office, _ = BuildingType.objects.update_or_create(
        key="tax_office",
        defaults={
            "name": "税务司",
            "description": "征收赋税，源源不断地产出银两。",
            "resource_type": "silver",
            "base_rate_per_hour": 90,
            "rate_growth": 0.17,
            "base_upgrade_time": 210,
            "time_growth": 1.25,
            "base_cost": {"wood": 180, "stone": 150, "iron": 120},
            "cost_growth": 1.36,
            "icon": "tax",
        },
    )

    TaskTemplate.objects.update_or_create(
        key="silver_stockpile",
        defaults={
            "name": "储银开支",
            "description": "将银两储备提高到 1,500 以上，以支撑更高级的招募。",
            "target_type": "resource_amount",
            "resource_type": "silver",
            "target_value": 1500,
            "reward": {"wood": 200, "grain": 200},
            "sort_order": 40,
        },
    )

    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=tax_office)


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0004_manor_add_silver"),
    ]

    operations = [
        migrations.RunPython(add_tax_office, migrations.RunPython.noop),
    ]
