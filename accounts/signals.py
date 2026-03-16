from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from accounts.utils import purge_other_sessions

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def sync_active_session_on_login(sender, request, user, **kwargs):
    del sender, kwargs
    try:
        request.session.save()
        purge_other_sessions(user.id, request.session.session_key)
    except Exception:
        logger.warning("Failed to sync active session on login for user %s", user.id, exc_info=True)
