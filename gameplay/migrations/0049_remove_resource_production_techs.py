"""
删除生产技术中的伐木术、采石术、冶铁术

这些技术已从配置中移除，此迁移清理数据库中的相关记录。
"""

from django.db import migrations


def remove_techs(apps, schema_editor):
    PlayerTechnology = apps.get_model("gameplay", "PlayerTechnology")

    # 删除玩家的这三个技术记录
    tech_keys = ["logging", "quarrying", "smelting"]
    deleted, _ = PlayerTechnology.objects.filter(tech_key__in=tech_keys).delete()
    if deleted:
        print(f"已删除 {deleted} 条技术记录")


def noop(apps, schema_editor):
    # 回滚时不执行任何操作（技术数据无法恢复）
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0048_add_tavern"),
    ]

    operations = [
        migrations.RunPython(remove_techs, noop),
    ]
