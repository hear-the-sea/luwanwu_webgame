from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import GearTemplate, GuestTemplate
from .services import give_gear


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def grant_initial_gear(sender, instance, created, **kwargs):
    if not created:
        return
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(instance)
    template = GearTemplate.objects.first()
    if template:
        give_gear(manor, template)


@receiver([post_save, post_delete], sender=GuestTemplate)
def clear_guest_template_cache(sender, **kwargs):
    """
    GuestTemplate 变更时清理招募模板缓存，避免运行中使用陈旧数据。
    """
    if kwargs.get("raw"):  # 跳过数据迁移
        return

    try:
        from .services.recruitment import clear_template_cache

        clear_template_cache()
    except Exception as e:
        # Best-effort: cache clear should never break writes.
        import logging

        logger = logging.getLogger(__name__)
        logger.warning("Failed to clear guest template cache: %s", e, exc_info=True)
