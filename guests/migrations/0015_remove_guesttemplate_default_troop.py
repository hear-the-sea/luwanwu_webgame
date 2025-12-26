from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0014_populate_default_troop"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="guesttemplate",
            name="default_troop",
        ),
    ]
