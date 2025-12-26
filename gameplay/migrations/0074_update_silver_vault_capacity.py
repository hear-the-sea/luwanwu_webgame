from django.db import migrations


def update_silver_vault(apps, schema_editor):
    """
    更新银库配置：
    - 满级从20级提升到30级
    - 满级容量从1050万提升到4000万
    - 更新建筑描述
    """
    BuildingType = apps.get_model("gameplay", "BuildingType")

    BuildingType.objects.filter(key="silver_vault").update(
        description="存放银两的库房，等级越高存储上限越高。满级(30级)可存储4000万两银子。",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0073_update_youxibaota_config"),
    ]

    operations = [
        migrations.RunPython(update_silver_vault, migrations.RunPython.noop),
    ]
