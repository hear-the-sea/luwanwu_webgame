"""Shared helpers (prefer no app imports; safe to use across apps)."""

from __future__ import annotations

from .celery import safe_apply_async
from .loot import resolve_drop_rewards

__all__ = [
    "resolve_drop_rewards",
    "safe_apply_async",
]
