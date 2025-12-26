from django.db import migrations, models

import guests.models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0015_remove_guesttemplate_default_troop"),
    ]

    operations = [
        migrations.AddField(
            model_name="skill",
            name="kind",
            field=models.CharField(
                choices=[("active", "主动"), ("passive", "被动")],
                default=guests.models.SkillKind.ACTIVE,
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="status_effect",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="skill",
            name="status_probability",
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name="skill",
            name="status_duration",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
