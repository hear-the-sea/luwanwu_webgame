# Generated manually
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0043_add_bathhouse_latrine"),
    ]

    operations = [
        migrations.AddField(
            model_name="manor",
            name="prestige",
            field=models.PositiveIntegerField(default=0, verbose_name="声望"),
        ),
        migrations.AddField(
            model_name="manor",
            name="prestige_silver_spent",
            field=models.PositiveIntegerField(default=0, verbose_name="累计花费银两（声望计算用）"),
        ),
    ]
