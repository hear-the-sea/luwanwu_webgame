from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def ping() -> str:
    logger.info("Demo Celery task executed.")
    return "pong"

