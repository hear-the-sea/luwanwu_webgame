from django.db import migrations


def remove_iron_mine(apps, schema_editor):
    """删除废弃的 iron_mine 建筑"""
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")

    # 先删除玩家的建筑实例
    Building.objects.filter(building_type__key="iron_mine").delete()
    # 再删除建筑类型
    BuildingType.objects.filter(key="iron_mine").delete()


def reverse_remove(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0067_funny_building_descriptions"),
    ]

    operations = [
        migrations.RunPython(remove_iron_mine, reverse_remove),
    ]
