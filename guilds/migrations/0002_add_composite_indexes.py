from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('guilds', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='guildapplication',
            index=models.Index(
                fields=['guild', 'status', '-created_at'],
                name='gapp_guild_sts_cr_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='guildwarehouse',
            index=models.Index(
                fields=['guild', '-contribution_cost'],
                name='guildwh_guild_contrib_idx',
            ),
        ),
    ]
