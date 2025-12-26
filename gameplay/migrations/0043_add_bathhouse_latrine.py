# Generated manually
from django.db import migrations


def add_bathhouse_latrine(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    # 澡堂 - 满级(20)每小时得1000两银子，门客生命恢复200%
    # 1级产出 = 1000 / (1 + 0.1 * 19) = 1000 / 2.9 ≈ 345
    # 使用 base_rate = 50，rate_growth = 0.1，20级产出 = 50 * (1 + 0.1*19) = 50 * 2.9 = 145
    # 调整：base_rate = 345，rate_growth = 0.1，20级产出 = 345 * 2.9 ≈ 1000
    bathhouse, _ = BuildingType.objects.update_or_create(
        key="bathhouse",
        defaults={
            "name": "澡堂",
            "description": "庄园澡堂，门客可在此沐浴休憩。每小时产出银两，并提升门客生命恢复速度。满级(20级)每小时产银1000两，门客生命恢复+200%。",
            "resource_type": "silver",
            "base_rate_per_hour": 345,
            "rate_growth": 0.10,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"wood": 200, "stone": 150, "silver": 500},
            "cost_growth": 1.35,
            "icon": "bathhouse",
        },
    )

    # 茅厕 - 满级(20)每小时增产粮食1000，得银子1000两
    # 粮食产出用 grain 资源类型
    # 银两产出需要特殊处理
    # 1级产出 = 1000 / 2.9 ≈ 345
    latrine, _ = BuildingType.objects.update_or_create(
        key="latrine",
        defaults={
            "name": "茅厕",
            "description": "庄园茅厕，可将废物转化为肥料。每小时增产粮食和银两。满级(20级)每小时产粮1000、产银1000两。",
            "resource_type": "grain",
            "base_rate_per_hour": 345,
            "rate_growth": 0.10,
            "base_upgrade_time": 300,
            "time_growth": 1.25,
            "base_cost": {"wood": 150, "stone": 100, "silver": 300},
            "cost_growth": 1.35,
            "icon": "latrine",
        },
    )

    # 为所有现有庄园创建这两个建筑
    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=bathhouse)
        Building.objects.get_or_create(manor=manor, building_type=latrine)


def remove_bathhouse_latrine(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key__in=["bathhouse", "latrine"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gameplay', '0042_add_silver_grain_capacity'),
    ]

    operations = [
        migrations.RunPython(add_bathhouse_latrine, remove_bathhouse_latrine, elidable=True),
    ]
