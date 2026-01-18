"""
添加监牢与结义林建筑类型，并为现有庄园补齐建筑实例。

约束：
- 监牢：仅用于控制可关押俘虏人数上限（满级5人）
- 结义林：仅用于控制可结义门客人数上限（满级5人）
"""

from django.db import migrations


def create_buildings(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    jail, _ = BuildingType.objects.update_or_create(
        key="jail",
        defaults={
            "name": "监牢",
            "description": "牢门一闭，江湖恩怨自有去处。踢馆胜利后有概率俘获对方出战门客（单场最多1名）。升级提升可关押人数上限（满级5人）。",
            "category": "special",
            "resource_type": "silver",
            "base_rate_per_hour": 0,
            "rate_growth": 0.0,
            "base_upgrade_time": 600,
            "time_growth": 1.35,
            "base_cost": {"silver": 1200, "grain": 800},
            "cost_growth": 1.4,
            "icon": "",
        },
    )

    oath_grove, _ = BuildingType.objects.update_or_create(
        key="oath_grove",
        defaults={
            "name": "结义林",
            "description": "桃园结义，义薄云天。最多可与5名门客结义，结义门客不可被俘获。升级提升结义人数上限（满级5人）。",
            "category": "special",
            "resource_type": "silver",
            "base_rate_per_hour": 0,
            "rate_growth": 0.0,
            "base_upgrade_time": 600,
            "time_growth": 1.35,
            "base_cost": {"silver": 1200, "grain": 800},
            "cost_growth": 1.4,
            "icon": "",
        },
    )

    for manor in Manor.objects.all().iterator():
        Building.objects.get_or_create(manor=manor, building_type=jail)
        Building.objects.get_or_create(manor=manor, building_type=oath_grove)


def remove_buildings(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key__in=["jail", "oath_grove"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0085_jailprisoner_oathbond"),
    ]

    operations = [
        migrations.RunPython(create_buildings, remove_buildings),
    ]

