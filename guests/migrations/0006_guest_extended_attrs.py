from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0005_update_slots"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="force",
            field=models.PositiveIntegerField(default=80, verbose_name="武力"),
        ),
        migrations.AddField(
            model_name="guest",
            name="intellect",
            field=models.PositiveIntegerField(default=80, verbose_name="智力"),
        ),
        migrations.AddField(
            model_name="guest",
            name="defense_stat",
            field=models.PositiveIntegerField(default=80, verbose_name="防御"),
        ),
        migrations.AddField(
            model_name="guest",
            name="agility",
            field=models.PositiveIntegerField(default=80, verbose_name="敏捷"),
        ),
        migrations.AddField(
            model_name="guest",
            name="luck",
            field=models.PositiveIntegerField(default=50, verbose_name="运势"),
        ),
        migrations.AddField(
            model_name="guest",
            name="loyalty",
            field=models.PositiveIntegerField(default=80, verbose_name="忠诚度"),
        ),
        migrations.AddField(
            model_name="guest",
            name="gender",
            field=models.CharField(
                choices=[("male", "男"), ("female", "女"), ("unknown", "未知")],
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="guest",
            name="morality",
            field=models.CharField(
                choices=[("just", "刚正"), ("neutral", "中庸"), ("evil", "桀骜")],
                default="neutral",
                max_length=16,
            ),
        ),
    ]
