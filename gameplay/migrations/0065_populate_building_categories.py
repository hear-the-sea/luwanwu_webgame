from django.db import migrations


def set_building_categories(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")

    # 资源生产类建筑
    resource_keys = ["farm", "tax_office", "bathhouse", "latrine"]
    BuildingType.objects.filter(key__in=resource_keys).update(category="resource")

    # 仓储设施类建筑
    storage_keys = ["granary", "silver_vault", "treasury"]
    BuildingType.objects.filter(key__in=storage_keys).update(category="storage")

    # 生产加工类建筑
    production_keys = ["ranch", "stable", "smithy", "forge", "iron_mine"]
    BuildingType.objects.filter(key__in=production_keys).update(category="production")

    # 人员管理类建筑
    personnel_keys = ["juxianzhuang", "jiadingfang", "lianggongchang", "tavern"]
    BuildingType.objects.filter(key__in=personnel_keys).update(category="personnel")

    # 特殊建筑
    special_keys = ["citang", "youxibaota"]
    BuildingType.objects.filter(key__in=special_keys).update(category="special")


def reverse_categories(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")
    BuildingType.objects.all().update(category="resource")


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0064_add_building_category"),
    ]

    operations = [
        migrations.RunPython(set_building_categories, reverse_categories),
    ]
