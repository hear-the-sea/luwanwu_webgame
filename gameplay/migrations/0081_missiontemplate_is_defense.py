from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0080_auction_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="missiontemplate",
            name="is_defense",
            field=models.BooleanField(default=False, help_text="敌方主动来袭，玩家为防守方"),
        ),
    ]
