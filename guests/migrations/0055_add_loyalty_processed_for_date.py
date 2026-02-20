from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0054_add_xisuidan_used"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="loyalty_processed_for_date",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text="记录最近一次每日忠诚度结算的日期，用于避免重复执行",
                null=True,
                verbose_name="忠诚度处理日期",
            ),
        ),
    ]

