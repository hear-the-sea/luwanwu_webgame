from django.db import migrations


def create_building_types(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    building_data = [
        {
            "key": "lumber_yard",
            "name": "伐木场",
            "description": "提供庄园建设所需的木材。",
            "resource_type": "wood",
            "base_rate_per_hour": 120,
            "rate_growth": 0.18,
            "base_upgrade_time": 180,
            "time_growth": 1.25,
            "base_cost": {"wood": 120, "stone": 60},
            "cost_growth": 1.35,
        },
        {
            "key": "stone_pit",
            "name": "采石场",
            "description": "稳步产出石料，提升城防。",
            "resource_type": "stone",
            "base_rate_per_hour": 90,
            "rate_growth": 0.16,
            "base_upgrade_time": 210,
            "time_growth": 1.3,
            "base_cost": {"wood": 140, "stone": 80},
            "cost_growth": 1.35,
        },
        {
            "key": "iron_mine",
            "name": "铁匠铺",
            "description": "供应兵器锻造所需的铁矿。",
            "resource_type": "iron",
            "base_rate_per_hour": 70,
            "rate_growth": 0.2,
            "base_upgrade_time": 240,
            "time_growth": 1.32,
            "base_cost": {"wood": 160, "stone": 120, "iron": 40},
            "cost_growth": 1.4,
        },
        {
            "key": "farm",
            "name": "农田",
            "description": "产出粮食，保障军队行动。",
            "resource_type": "grain",
            "base_rate_per_hour": 150,
            "rate_growth": 0.14,
            "base_upgrade_time": 180,
            "time_growth": 1.22,
            "base_cost": {"wood": 100, "stone": 70},
            "cost_growth": 1.33,
        },
    ]
    for data in building_data:
        BuildingType.objects.update_or_create(key=data["key"], defaults=data)


def create_tasks(apps, schema_editor):
    TaskTemplate = apps.get_model("gameplay", "TaskTemplate")
    task_data = [
        {
            "key": "upgrade_first",
            "name": "首次升级",
            "description": "任意建筑升至 2 级，解锁更高产能。",
            "target_type": "building_level",
            "target_value": 2,
            "reward": {"wood": 300, "stone": 200},
            "sort_order": 10,
        },
        {
            "key": "wood_stockpile",
            "name": "储备木材",
            "description": "木材达到 1,500，确保持续建设。",
            "target_type": "resource_amount",
            "resource_type": "wood",
            "target_value": 1500,
            "reward": {"stone": 150, "iron": 60},
            "sort_order": 20,
        },
        {
            "key": "grain_stockpile",
            "name": "粮草充足",
            "description": "粮食储量达到 2,000，支持远征。",
            "target_type": "resource_amount",
            "resource_type": "grain",
            "target_value": 2000,
            "reward": {"wood": 150, "stone": 120},
            "sort_order": 30,
        },
    ]
    for data in task_data:
        TaskTemplate.objects.update_or_create(key=data["key"], defaults=data)


def forwards(apps, schema_editor):
    create_building_types(apps, schema_editor)
    create_tasks(apps, schema_editor)


def backwards(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    TaskTemplate = apps.get_model("gameplay", "TaskTemplate")
    BuildingType.objects.filter(key__in=["lumber_yard", "stone_pit", "iron_mine", "farm"]).delete()
    TaskTemplate.objects.filter(key__in=["upgrade_first", "wood_stockpile", "grain_stockpile"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
