"""
蒲巴乙门客模板种子数据
"""

from django.db import migrations


def seed_pubayi_templates(apps, schema_editor):
    """创建蒲巴乙门客模板（绿色和蓝色两个版本）"""
    GuestTemplate = apps.get_model("guests", "GuestTemplate")

    templates = [
        {
            "key": "pubayi_green",
            "name": "蒲巴乙",
            "archetype": "civil",
            "rarity": "green",
            "base_attack": 70,
            "base_intellect": 85,
            "base_defense": 65,
            "base_agility": 75,
            "base_luck": 60,
            "base_hp": 1000,
            "flavor": "性格温和的普通人，勤勤恳恳。",
            "default_gender": "male",
            "default_morality": 60,
            "recruitable": False,  # 不参与常规招募
        },
        {
            "key": "pubayi_blue",
            "name": "蒲巴乙",
            "archetype": "civil",
            "rarity": "blue",
            "base_attack": 90,
            "base_intellect": 110,
            "base_defense": 85,
            "base_agility": 95,
            "base_luck": 80,
            "base_hp": 1200,
            "flavor": "眼神中透露出不凡的气质，或许有着不为人知的过往。",
            "default_gender": "male",
            "default_morality": 70,
            "recruitable": False,  # 不参与常规招募
        },
    ]

    for data in templates:
        GuestTemplate.objects.update_or_create(key=data["key"], defaults=data)


def reverse_pubayi_templates(apps, schema_editor):
    """回滚：删除蒲巴乙门客模板"""
    GuestTemplate = apps.get_model("guests", "GuestTemplate")
    GuestTemplate.objects.filter(key__in=["pubayi_green", "pubayi_blue"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0048_guest_guest_training_idx"),
    ]

    operations = [
        migrations.RunPython(seed_pubayi_templates, reverse_pubayi_templates),
    ]
