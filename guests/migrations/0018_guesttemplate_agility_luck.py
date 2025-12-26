from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0017_remove_guesttemplate_default_skills"),
    ]

    operations = [
        migrations.AddField(
            model_name="guesttemplate",
            name="base_agility",
            field=models.PositiveIntegerField(default=80),
        ),
        migrations.AddField(
            model_name="guesttemplate",
            name="base_luck",
            field=models.PositiveIntegerField(default=50),
        ),
    ]
