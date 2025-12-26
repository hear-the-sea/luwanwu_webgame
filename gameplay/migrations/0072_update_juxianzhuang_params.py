from django.db import migrations


def update_juxianzhuang_params(apps, schema_editor):
    """
    更新聚贤庄升级参数：
    - 满级15级，最多容纳18位门客
    - 0→1级：2万银两（前期不能太简单）
    - 14→15级：约2217万银两 + 1663万粮食
    - 升级成本和时间呈指数增长，参考其他重要建筑
    """
    BuildingType = apps.get_model("gameplay", "BuildingType")

    BuildingType.objects.filter(key="juxianzhuang").update(
        base_cost={"silver": 20000, "grain": 15000},
        cost_growth=1.65,
        base_upgrade_time=600,
        time_growth=1.3,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0071_scout_return_phase"),
    ]

    operations = [
        migrations.RunPython(update_juxianzhuang_params, migrations.RunPython.noop),
    ]
