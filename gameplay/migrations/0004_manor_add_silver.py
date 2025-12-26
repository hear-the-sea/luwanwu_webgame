from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0003_backfill_manors"),
    ]

    operations = [
        migrations.AddField(
            model_name="manor",
            name="silver",
            field=models.PositiveIntegerField(default=500, verbose_name="银两"),
        ),
    ]
