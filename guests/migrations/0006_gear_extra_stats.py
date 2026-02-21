from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0005_update_slots"),
    ]

    operations = [
        migrations.AddField(
            model_name="geartemplate",
            name="extra_stats",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
