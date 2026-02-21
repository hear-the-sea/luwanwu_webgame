"""
Guest template cache management.
"""

from __future__ import annotations

import logging
from typing import Dict

from django.core.cache import cache

from guests.models import GuestTemplate

logger = logging.getLogger(__name__)

# Cache configuration
GUEST_TEMPLATE_CACHE_KEY = "battle:guest_templates"
GUEST_TEMPLATE_CACHE_TTL = 300  # 5 minutes


def get_all_guest_templates() -> Dict[str, GuestTemplate]:
    """
    Get all guest templates (using Django cache for cross-process sharing).

    Security fix: Changed from @lru_cache to Django cache framework.
    - lru_cache is process-local, inconsistent in multi-process environments
    - Django cache (e.g., Redis) can be shared across processes
    """
    cached_keys = cache.get(GUEST_TEMPLATE_CACHE_KEY)
    if cached_keys is not None:
        return {t.key: t for t in GuestTemplate.objects.filter(key__in=cached_keys).prefetch_related("initial_skills")}

    from core.utils.template_loader import load_templates_by_key

    templates = load_templates_by_key(GuestTemplate, keys=None, prefetch=["initial_skills"])  # 加载全部
    cache.set(GUEST_TEMPLATE_CACHE_KEY, list(templates.keys()), timeout=GUEST_TEMPLATE_CACHE_TTL)
    return templates


def clear_guest_template_cache() -> None:
    """Clear guest template cache (call when templates change)."""
    cache.delete(GUEST_TEMPLATE_CACHE_KEY)
