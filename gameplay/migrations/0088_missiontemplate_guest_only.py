from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0087_jailprisoner_add_released_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="missiontemplate",
            name="guest_only",
            field=models.BooleanField(default=False, help_text="仅允许门客出征，不可带护院"),
        ),
    ]
