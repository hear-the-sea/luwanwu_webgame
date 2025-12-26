from django.db import migrations


def set_training_to_idle(apps, schema_editor):
    Guest = apps.get_model("guests", "Guest")
    Guest.objects.filter(status="training").update(status="idle")


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0030_cap_guest_level"),
    ]

    operations = [
        migrations.RunPython(set_training_to_idle, migrations.RunPython.noop),
    ]
