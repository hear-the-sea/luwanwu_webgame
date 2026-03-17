from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from logging import Logger
from typing import Any, TypeVar

RecordT = TypeVar("RecordT")

DEFAULT_TASK_DEDUP_TIMEOUT = 5


def maybe_reschedule_for_future(
    *,
    task_func,
    record_id: int,
    eta_value,
    dedup_key: str,
    schedule_func: Callable[..., bool],
    logger: Logger,
    now_func: Callable[[], Any],
    log_message: str,
    failure_message: str,
    dedup_timeout: int = DEFAULT_TASK_DEDUP_TIMEOUT,
) -> tuple[str | None, Any]:
    now = now_func()
    if eta_value and eta_value > now:
        remaining = math.ceil((eta_value - now).total_seconds())
        if remaining > 0:
            effective_dedup_timeout = max(int(remaining) + 60, dedup_timeout, 60)
            dispatched = schedule_func(
                task_func,
                dedup_key=dedup_key,
                dedup_timeout=effective_dedup_timeout,
                args=[record_id],
                countdown=remaining,
                logger=logger,
                log_message=log_message,
            )
            if not dispatched:
                raise RuntimeError(failure_message)
            return "rescheduled", now
    return None, now


def count_finalized_records(
    records: Iterable[RecordT],
    *,
    finalize: Callable[[RecordT], bool],
    logger: Logger,
    error_message: str,
) -> int:
    count = 0
    for record in records:
        try:
            if finalize(record):
                count += 1
        except Exception as exc:
            logger.exception(error_message, getattr(record, "id", None), exc)
    return count
