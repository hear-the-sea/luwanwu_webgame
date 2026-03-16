"""
Celery signal handlers for task monitoring.

Connects to Celery's built-in signals to automatically record task success,
failure, and retry events via :mod:`core.utils.task_monitoring`.

Signals are registered by calling :func:`connect_task_signals` from the Celery
app configuration (``config/celery.py``).
"""

from __future__ import annotations

import logging

from celery.signals import task_failure, task_retry, task_success

from core.utils.task_monitoring import record_task_failure, record_task_retry, record_task_success

logger = logging.getLogger(__name__)


def _on_task_success(sender=None, **kwargs):
    """Record a successful task execution."""
    task_name = getattr(sender, "name", None) or str(sender)
    record_task_success(task_name)


def _on_task_failure(sender=None, exception=None, traceback=None, **kwargs):
    """Record a task failure and log structured context."""
    task_name = getattr(sender, "name", None) or str(sender)
    record_task_failure(task_name)
    logger.error(
        "Celery task failed: %s (%s)",
        task_name,
        type(exception).__name__ if exception else "unknown",
        extra={
            "task_name": task_name,
            "exception_type": type(exception).__name__ if exception else None,
            "exception_message": str(exception) if exception else None,
        },
    )


def _on_task_retry(sender=None, reason=None, **kwargs):
    """Record a task retry and log structured context."""
    task_name = getattr(sender, "name", None) or str(sender)
    record_task_retry(task_name)
    logger.warning(
        "Celery task retrying: %s (reason: %s)",
        task_name,
        reason,
        extra={
            "task_name": task_name,
            "retry_reason": str(reason) if reason else None,
        },
    )


def connect_task_signals() -> None:
    """Register all Celery signal handlers. Safe to call multiple times."""
    task_success.connect(_on_task_success, weak=False)
    task_failure.connect(_on_task_failure, weak=False)
    task_retry.connect(_on_task_retry, weak=False)
