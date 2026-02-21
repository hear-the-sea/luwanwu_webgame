from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0020_add_youxibaota"),
    ]

    operations = [
        migrations.AddField(
            model_name="itemtemplate",
            name="rarity",
            field=models.CharField(default="gray", max_length=16),
        ),
    ]
