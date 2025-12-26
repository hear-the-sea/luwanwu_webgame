from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0026_guest_status"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="guest",
            name="morale",
        ),
    ]
