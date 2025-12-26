from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0028_remove_guest_breakthrough"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="training_complete_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="guest",
            name="training_target_level",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
