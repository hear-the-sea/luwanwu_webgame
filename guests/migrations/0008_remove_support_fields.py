from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0007_remove_base_support"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="guest",
            name="support_bonus",
        ),
        migrations.RemoveField(
            model_name="geartemplate",
            name="support_bonus",
        ),
    ]
