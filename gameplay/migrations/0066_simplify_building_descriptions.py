from django.db import migrations


def simplify_descriptions(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")

    descriptions = {
        # 资源生产
        "farm": "产出粮食，保障军队行动。",
        "tax_office": "征收赋税，源源不断地产出银两。",
        "bathhouse": "门客可在此沐浴休憩，产出银两并提升门客生命恢复速度。",
        "latrine": "可将废物转化为肥料，增产粮食和银两。",
        # 仓储设施
        "granary": "存放粮食的仓库，等级越高存储上限越高。",
        "silver_vault": "存放银两的库房，等级越高存储上限越高。",
        "treasury": "安全存储珍贵物品的建筑，藏宝阁中的物品不会被抢夺。",
        # 生产加工
        "iron_mine": "供应兵器锻造所需的铁矿。",
        "ranch": "饲养家畜的场所，等级越高制造速度越快。",
        "smithy": "冶炼金属的工坊，等级越高制造速度越快。",
        "stable": "饲养马匹的建筑，等级越高制造速度越快。",
        "forge": "锻造装备的工坊，等级越高锻造速度越快。",
        # 人员管理
        "juxianzhuang": "门客招募场所，等级越高可容纳的门客上限越高。",
        "jiadingfang": "安置家丁的营舍，等级越高可容纳的家丁越多。",
        "lianggongchang": "可将家丁训练为护院，等级越高训练速度越快。",
        "tavern": "江湖人士聚集的场所，增加银两收入和招募候选人数。",
        # 特殊建筑
        "citang": "庄园辉煌繁荣的象征，减少建筑时间并提升护院招募速度。",
        "youxibaota": "提升同时出征门客人数上限的特殊建筑。",
    }

    for key, desc in descriptions.items():
        BuildingType.objects.filter(key=key).update(description=desc)


def reverse_descriptions(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0065_populate_building_categories"),
    ]

    operations = [
        migrations.RunPython(simplify_descriptions, reverse_descriptions),
    ]
