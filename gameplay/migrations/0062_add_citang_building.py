"""
添加祠堂建筑

祠堂：庄园辉煌繁荣的象征，神圣不可侵犯。
- 满级5级
- 每升一级所有建筑设施时间减少20%
- 每升一级招募护院速度提升30%
- 建设需要花费大量的人物和财力
"""

from django.db import migrations


def create_citang(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")
    Manor = apps.get_model("gameplay", "Manor")

    # 祠堂：5级满级
    # 每级减少建筑升级时间20%，满级减少80%
    # 每级提升护院招募速度30%，满级提升120%
    # 建设成本高昂
    citang, _ = BuildingType.objects.update_or_create(
        key="citang",
        defaults={
            "name": "祠堂",
            "description": "庄园辉煌繁荣的象征，神圣不可侵犯。每升一级所有建筑设施时间减少20%，招募护院速度提升30%。满级(5级)建筑时间减少80%，护院招募速度提升120%。",
            "resource_type": "silver",
            "base_rate_per_hour": 0,
            "rate_growth": 0.0,
            "base_upgrade_time": 3600,  # 1小时基础建造时间
            "time_growth": 2.0,  # 升级时间增长较快
            "base_cost": {"silver": 10000, "grain": 5000},  # 高昂成本
            "cost_growth": 2.0,  # 成本增长系数较高
            "icon": "citang",
        },
    )

    # 为所有现有庄园创建祠堂
    for manor in Manor.objects.all():
        Building.objects.get_or_create(manor=manor, building_type=citang)


def remove_citang(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.filter(key="citang").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0061_add_manor_name"),
    ]

    operations = [
        migrations.RunPython(create_citang, remove_citang),
    ]
