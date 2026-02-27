import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0098_alter_manor_silver_default"),
    ]

    operations = [
        migrations.CreateModel(
            name="GlobalMailCampaign",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=64, unique=True, verbose_name="活动标识")),
                (
                    "kind",
                    models.CharField(
                        choices=[("battle", "战报"), ("system", "系统"), ("reward", "奖励")],
                        default="reward",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(max_length=128, verbose_name="标题")),
                ("body", models.TextField(blank=True, verbose_name="正文")),
                ("attachments", models.JSONField(blank=True, default=dict, verbose_name="附件数据")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="启用")),
                ("start_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="开始时间")),
                ("end_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="结束时间")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "全服邮件活动",
                "verbose_name_plural": "全服邮件活动",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="GlobalMailDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="投递时间")),
                (
                    "campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="gameplay.globalmailcampaign",
                        verbose_name="活动",
                    ),
                ),
                (
                    "manor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="global_mail_deliveries",
                        to="gameplay.manor",
                        verbose_name="庄园",
                    ),
                ),
                (
                    "message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="global_mail_deliveries",
                        to="gameplay.message",
                        verbose_name="消息",
                    ),
                ),
            ],
            options={
                "verbose_name": "全服邮件投递记录",
                "verbose_name_plural": "全服邮件投递记录",
            },
        ),
        migrations.AddConstraint(
            model_name="globalmaildelivery",
            constraint=models.UniqueConstraint(fields=("campaign", "manor"), name="uniq_global_mail_campaign_manor"),
        ),
        migrations.AddIndex(
            model_name="globalmailcampaign",
            index=models.Index(fields=["is_active", "start_at", "end_at"], name="global_mail_active_idx"),
        ),
        migrations.AddIndex(
            model_name="globalmaildelivery",
            index=models.Index(fields=["campaign", "-created_at"], name="global_mail_deliver_c_idx"),
        ),
        migrations.AddIndex(
            model_name="globalmaildelivery",
            index=models.Index(fields=["manor", "-created_at"], name="global_mail_deliver_m_idx"),
        ),
    ]
