from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import bootstrap_manor


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_manor_for_user(sender, instance, created, **kwargs):
    if created:
        # 从用户的注册数据中获取地区与庄园名（在 RegisterView 中设置）
        region = getattr(instance, "_signup_region", "overseas")
        manor_name = getattr(instance, "_signup_manor_name", "")
        bootstrap_manor(instance, region=region, initial_name=manor_name)
