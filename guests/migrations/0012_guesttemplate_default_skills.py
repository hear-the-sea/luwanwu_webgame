from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0011_alter_guestskill_unique_together"),
    ]

    operations = [
        migrations.AddField(
            model_name="guesttemplate",
            name="default_skills",
            field=models.JSONField(default=list),
        ),
    ]
