from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0006_gear_extra_stats"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="guesttemplate",
            name="base_support",
        ),
    ]

