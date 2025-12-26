from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0024_alter_itemtemplate_effect_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="itemtemplate",
            name="price",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="itemtemplate",
            name="tradeable",
            field=models.BooleanField(default=False),
        ),
    ]
