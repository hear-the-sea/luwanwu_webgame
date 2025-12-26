from django.db import migrations


def update_descriptions(apps, schema_editor):
    BuildingType = apps.get_model("gameplay", "BuildingType")

    descriptions = {
        # 资源生产
        "farm": "面朝黄土背朝天，种出来的粮食养活一大家子。升级提升粮食产量",
        "tax_office": "合法抢钱的地方，百姓的钱包在哭泣。升级提升银两产量",
        "bathhouse": "泡澡搓背一条龙，门客洗完精神抖擞。升级提升银两产量和门客恢复速度",
        "latrine": "变废为宝的神奇建筑，屎尿也能生钱。升级提升粮食和银两产量",
        # 仓储设施
        "granary": "囤粮防饥荒，老鼠看了直流口水。升级提升粮食存储上限",
        "silver_vault": "金山银山堆这里，小偷做梦都想来。升级提升银两存储上限",
        "treasury": "藏宝阁里藏宝贝，强盗来了也白搭。升级提升物品存储上限",
        # 生产加工
        "iron_mine": "挖矿工人的噩梦，铁矿石的老家。升级提升铁矿产量",
        "ranch": "鸡鸭鹅猪牛的快乐老家，直到被端上餐桌。升级提升制造速度",
        "smithy": "烧火炼铁的地方，热得像蒸笼。升级提升冶炼速度",
        "stable": "马儿们的豪华公寓，吃好喝好跑得快。升级提升驯马速度",
        "forge": "叮叮当当打铁铺，装备全靠这里出。升级提升锻造速度",
        # 人员管理
        "juxianzhuang": "英雄好汉聚集地，有钱就能挖墙脚。升级提升门客容纳上限",
        "jiadingfang": "家丁们的集体宿舍，挤一挤更暖和。升级提升家丁容纳上限",
        "lianggongchang": "把废柴练成高手的神奇地方。升级提升训练速度",
        "tavern": "喝酒吹牛交朋友，消息灵通人脉广。升级提升银两收入和招募候选人数",
        # 特殊建筑
        "citang": "祖宗保佑发大财，庄园门面担当。升级减少建筑时间并提升招募速度",
        "youxibaota": "指挥塔楼望四方，出征人数看这里。升级提升同时出征门客上限",
    }

    for key, desc in descriptions.items():
        BuildingType.objects.filter(key=key).update(description=desc)


def reverse_descriptions(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0066_simplify_building_descriptions"),
    ]

    operations = [
        migrations.RunPython(update_descriptions, reverse_descriptions),
    ]
