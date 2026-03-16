from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from accounts.utils import purge_other_sessions
from core.utils.degradation import SESSION_SYNC_FAILURE, record_degradation

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def sync_active_session_on_login(sender, request, user, **kwargs):
    del sender, kwargs
    try:
        request.session.save()
        success = purge_other_sessions(user.id, request.session.session_key)
        if not success:
            logger.warning(
                "Single-session enforcement may have failed for user %s",
                user.id,
                extra={"user_id": user.id, "degraded": True},
            )
            record_degradation(
                SESSION_SYNC_FAILURE,
                component="sync_active_session_on_login",
                detail="purge_other_sessions returned False",
                user_id=user.id,
            )
    except Exception:
        logger.warning("Failed to sync active session on login for user %s", user.id, exc_info=True)
