from django.db import migrations


def rename_tongshi_pool_to_cunmu(apps, schema_editor):
    RecruitmentPool = apps.get_model("guests", "RecruitmentPool")
    RecruitmentPoolEntry = apps.get_model("guests", "RecruitmentPoolEntry")
    RecruitmentRecord = apps.get_model("guests", "RecruitmentRecord")
    RecruitmentCandidate = apps.get_model("guests", "RecruitmentCandidate")
    GuestRecruitment = apps.get_model("guests", "GuestRecruitment")

    old_qs = RecruitmentPool.objects.filter(key="tongshi").order_by("id")
    old_ids = list(old_qs.values_list("id", flat=True))

    target = RecruitmentPool.objects.filter(key="cunmu").order_by("id").first()
    if target is None and old_ids:
        target = old_qs.first()
        RecruitmentPool.objects.filter(pk=target.pk).update(key="cunmu", tier="cunmu")

    if target is not None:
        target_id = target.pk
        RecruitmentPool.objects.filter(pk=target_id).update(tier="cunmu")

        migrate_ids = [pool_id for pool_id in old_ids if pool_id != target_id]
        if migrate_ids:
            RecruitmentPoolEntry.objects.filter(pool_id__in=migrate_ids).update(pool_id=target_id)
            RecruitmentRecord.objects.filter(pool_id__in=migrate_ids).update(pool_id=target_id)
            RecruitmentCandidate.objects.filter(pool_id__in=migrate_ids).update(pool_id=target_id)
            GuestRecruitment.objects.filter(pool_id__in=migrate_ids).update(pool_id=target_id)
            RecruitmentPool.objects.filter(id__in=migrate_ids).delete()

    RecruitmentPool.objects.filter(tier="tongshi").update(tier="cunmu")


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0057_guestrecruitment"),
    ]

    operations = [
        migrations.RunPython(rename_tongshi_pool_to_cunmu, migrations.RunPython.noop),
    ]
