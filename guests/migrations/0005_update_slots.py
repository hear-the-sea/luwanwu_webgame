from django.db import migrations


def forwards(apps, schema_editor):
    GearTemplate = apps.get_model("guests", "GearTemplate")
    GearTemplate.objects.filter(slot="accessory").update(slot="ornament")


def backwards(apps, schema_editor):
    GearTemplate = apps.get_model("guests", "GearTemplate")
    GearTemplate.objects.filter(slot="ornament").update(slot="accessory")


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0004_update_recruitment_data"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
