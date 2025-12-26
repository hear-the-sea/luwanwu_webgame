from django.db import migrations


def cap_levels(apps, schema_editor):
    Guest = apps.get_model("guests", "Guest")
    for guest in Guest.objects.all():
        if guest.level > 100:
            guest.level = 100
            guest.save(update_fields=["level"])


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0029_guest_training_fields"),
    ]

    operations = [
        migrations.RunPython(cap_levels, migrations.RunPython.noop),
    ]
