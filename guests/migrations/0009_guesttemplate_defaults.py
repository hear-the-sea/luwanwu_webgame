from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0008_guest_morality_int"),
    ]

    operations = [
        migrations.AddField(
            model_name="guesttemplate",
            name="default_gender",
            field=models.CharField(
                choices=[("male", "男"), ("female", "女"), ("unknown", "未知")], default="unknown", max_length=16
            ),
        ),
        migrations.AddField(
            model_name="guesttemplate",
            name="default_morality",
            field=models.PositiveIntegerField(default=50),
        ),
    ]
