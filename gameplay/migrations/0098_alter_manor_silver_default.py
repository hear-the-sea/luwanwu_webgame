from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0097_workassignment_unique_working_per_work"),
    ]

    operations = [
        migrations.AlterField(
            model_name="manor",
            name="silver",
            field=models.PositiveIntegerField(default=5000, verbose_name="银两"),
        ),
    ]
