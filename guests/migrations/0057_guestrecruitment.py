from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0091_troopbankstorage"),
        ("guests", "0056_add_salarypayment_for_date_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="GuestRecruitment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cost", models.JSONField(default=dict, verbose_name="招募消耗")),
                ("draw_count", models.PositiveIntegerField(default=1, verbose_name="候选数量")),
                ("duration_seconds", models.PositiveIntegerField(default=0, verbose_name="招募时长(秒)")),
                ("seed", models.BigIntegerField(default=0, verbose_name="随机种子")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "招募中"), ("completed", "已完成"), ("failed", "失败")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True, verbose_name="开始时间")),
                ("complete_at", models.DateTimeField(verbose_name="完成时间")),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="实际完成时间")),
                ("result_count", models.PositiveIntegerField(default=0, verbose_name="实际生成候选")),
                ("error_message", models.CharField(blank=True, default="", max_length=255, verbose_name="失败原因")),
                (
                    "manor",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE, related_name="guest_recruitments", to="gameplay.manor"
                    ),
                ),
                ("pool", models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, to="guests.recruitmentpool")),
            ],
            options={
                "verbose_name": "门客招募队列",
                "verbose_name_plural": "门客招募队列",
                "ordering": ("-started_at",),
            },
        ),
        migrations.AddIndex(
            model_name="guestrecruitment",
            index=models.Index(fields=["manor", "status", "complete_at"], name="guest_recruit_msc_idx"),
        ),
        migrations.AddIndex(
            model_name="guestrecruitment",
            index=models.Index(fields=["status", "complete_at"], name="guest_recruit_sc_idx"),
        ),
    ]
