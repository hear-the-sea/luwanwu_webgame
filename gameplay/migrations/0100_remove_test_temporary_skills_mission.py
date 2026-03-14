from django.db import migrations


def remove_test_temporary_skills_mission(apps, schema_editor):
    MissionTemplate = apps.get_model("gameplay", "MissionTemplate")
    MissionTemplate.objects.filter(key="test_temporary_skills").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0099_global_mail_campaign_and_delivery"),
    ]

    operations = [
        migrations.RunPython(remove_test_temporary_skills_mission, migrations.RunPython.noop),
    ]
