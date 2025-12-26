from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0032_merge_support_cleanup"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="last_hp_recovery_at",
            field=models.DateTimeField(default=timezone.now),
        ),
    ]

