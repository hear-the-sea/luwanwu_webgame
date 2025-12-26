from django.db import migrations, models


def forwards(apps, schema_editor):
    Guest = apps.get_model("guests", "Guest")
    mapping = {"just": 85, "neutral": 50, "evil": 30}
    for guest in Guest.objects.all():
        guest.morality_score = mapping.get(getattr(guest, "morality", "neutral"), 50)
        guest.save(update_fields=["morality_score"])


def backwards(apps, schema_editor):
    Guest = apps.get_model("guests", "Guest")
    reverse_mapping = [(80, "just"), (50, "neutral"), (30, "evil")]
    for guest in Guest.objects.all():
        value = "neutral"
        for threshold, label in reverse_mapping:
            if guest.morality >= threshold:
                value = label
                break
        guest.morality = value
        guest.save(update_fields=["morality"])


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0007_alter_geartemplate_slot"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="morality_score",
            field=models.PositiveIntegerField(default=50, verbose_name="品性"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="guest",
            name="morality",
        ),
        migrations.RenameField(
            model_name="guest",
            old_name="morality_score",
            new_name="morality",
        ),
    ]
