from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0016_skill_kind"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="guesttemplate",
            name="default_skills",
        ),
    ]
