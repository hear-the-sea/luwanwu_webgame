"""
战斗系统信号处理
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import TroopTemplate
from .troops import invalidate_troop_templates_cache


@receiver([post_save, post_delete], sender=TroopTemplate)
def clear_troop_templates_cache(sender, **kwargs):
    """
    TroopTemplate 变更时清除缓存
    """
    invalidate_troop_templates_cache()
