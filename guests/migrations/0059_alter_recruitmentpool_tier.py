from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0058_rename_tongshi_pool_to_cunmu"),
    ]

    operations = [
        migrations.AlterField(
            model_name="recruitmentpool",
            name="tier",
            field=models.CharField(
                choices=[("cunmu", "村募"), ("xiangshi", "乡试"), ("huishi", "会试"), ("dianshi", "殿试")],
                default="cunmu",
                max_length=16,
            ),
        ),
    ]
