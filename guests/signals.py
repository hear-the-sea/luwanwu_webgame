from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from gameplay.services import ensure_manor

from .models import GearTemplate
from .services import give_gear


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def grant_initial_gear(sender, instance, created, **kwargs):
    if not created:
        return
    manor = ensure_manor(instance)
    template = GearTemplate.objects.first()
    if template:
        give_gear(manor, template)
