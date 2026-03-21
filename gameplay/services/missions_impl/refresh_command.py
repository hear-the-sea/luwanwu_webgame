from __future__ import annotations

import math
from typing import Any

from core.utils.imports import is_missing_target_import


def refresh_mission_runs(
    manor,
    *,
    prefer_async: bool = False,
    mission_run_model,
    settings_obj,
    logger,
    now_func,
    try_dispatch_mission_refresh_task,
    finalize_mission_run,
) -> None:
    now = now_func()
    due_run_ids = list(
        manor.mission_runs.filter(
            status=mission_run_model.Status.ACTIVE,
            return_at__isnull=False,
            return_at__lte=now,
        ).values_list("id", flat=True)
    )
    if not due_run_ids:
        return

    sync_run_ids = due_run_ids
    sync_max_runs = max(0, int(getattr(settings_obj, "MISSION_REFRESH_SYNC_MAX_RUNS", 3)))
    should_try_async = prefer_async or len(due_run_ids) > sync_max_runs

    if should_try_async:
        try:
            from gameplay.tasks import complete_mission_task
        except ImportError as exc:
            if not is_missing_target_import(exc, "gameplay.tasks"):
                raise
            logger.warning(
                "Failed to import mission task, falling back to sync refresh: %s",
                exc,
                exc_info=True,
                extra={"degraded": True, "component": "mission_task_import"},
            )
        except Exception:
            logger.error(
                "Unexpected mission task import failure during refresh",
                exc_info=True,
                extra={"degraded": True, "component": "mission_task_import"},
            )
            raise
        else:
            sync_run_ids = []
            for run_id in due_run_ids:
                if not try_dispatch_mission_refresh_task(complete_mission_task, run_id):
                    sync_run_ids.append(run_id)

            if not sync_run_ids:
                return

    active_runs = list(
        mission_run_model.objects.select_related("mission")
        .prefetch_related("guests")
        .filter(id__in=sync_run_ids)
        .order_by("return_at")
    )
    for run in active_runs:
        finalize_mission_run(run, now=now)


def schedule_mission_completion(
    run: Any,
    *,
    logger,
    now_func,
    safe_apply_async,
    finalize_mission_run,
) -> None:
    if not run.return_at:
        return

    countdown = max(0, math.ceil((run.return_at - now_func()).total_seconds()))
    try:
        from gameplay.tasks import complete_mission_task
    except ImportError as exc:
        if not is_missing_target_import(exc, "gameplay.tasks"):
            raise
        logger.warning(
            "Unable to import complete_mission_task; relying on sync fallback when due: %s",
            exc,
            exc_info=True,
            extra={"degraded": True, "component": "mission_task_import"},
        )
        if countdown <= 0:
            finalize_mission_run(run)
        return
    except Exception:
        logger.error(
            "Unexpected complete_mission_task import failure",
            exc_info=True,
            extra={"degraded": True, "component": "mission_task_import"},
        )
        raise

    dispatched = safe_apply_async(
        complete_mission_task,
        args=[run.id],
        countdown=countdown,
        logger=logger,
        log_message="complete_mission_task dispatch failed; relying on refresh_mission_runs",
    )
    if not dispatched and countdown <= 0:
        logger.warning("complete_mission_task dispatch failed for due run; finalizing synchronously: run_id=%s", run.id)
        finalize_mission_run(run)
