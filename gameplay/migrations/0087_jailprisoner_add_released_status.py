"""
为JailPrisoner添加RELEASED状态选项。

用于标记已被释放的囚徒记录。
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0086_add_jail_and_oath_grove_buildings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jailprisoner",
            name="status",
            field=models.CharField(
                choices=[
                    ("held", "关押中"),
                    ("recruited", "已招募"),
                    ("released", "已释放"),
                ],
                db_index=True,
                default="held",
                max_length=16,
                verbose_name="状态",
            ),
        ),
    ]
