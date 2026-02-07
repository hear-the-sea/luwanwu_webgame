from __future__ import annotations

from typing import Dict, List

from django.db import IntegrityError, transaction

from ...models import Manor, MissionTemplate
from .time_utils import get_today_date_range


def get_mission_extra_attempts(manor: Manor, mission: MissionTemplate) -> int:
    from ...models import MissionExtraAttempt

    _, _, today_date = get_today_date_range()
    extra = MissionExtraAttempt.objects.filter(manor=manor, mission=mission, date=today_date).first()
    return extra.extra_count if extra else 0


def bulk_get_mission_extra_attempts(manor: Manor, missions: List[MissionTemplate]) -> Dict[str, int]:
    from ...models import MissionExtraAttempt

    _, _, today_date = get_today_date_range()
    extras = MissionExtraAttempt.objects.filter(manor=manor, date=today_date, mission__in=missions).select_related(
        "mission"
    )

    result = {m.key: 0 for m in missions}
    for extra in extras:
        result[extra.mission.key] = extra.extra_count
    return result


def add_mission_extra_attempt(manor: Manor, mission: MissionTemplate, count: int = 1) -> int:
    from ...models import MissionExtraAttempt

    _, _, today_date = get_today_date_range()
    with transaction.atomic():
        extra = (
            MissionExtraAttempt.objects.select_for_update()
            .filter(manor=manor, mission=mission, date=today_date)
            .first()
        )
        if extra:
            extra.extra_count += count
            extra.save(update_fields=["extra_count", "updated_at"])
            return extra.extra_count

    try:
        with transaction.atomic():
            extra = MissionExtraAttempt.objects.create(manor=manor, mission=mission, date=today_date, extra_count=count)
            return extra.extra_count
    except IntegrityError:
        with transaction.atomic():
            extra = MissionExtraAttempt.objects.select_for_update().get(manor=manor, mission=mission, date=today_date)
            extra.extra_count += count
            extra.save(update_fields=["extra_count", "updated_at"])
            return extra.extra_count


def get_mission_daily_limit(manor: Manor, mission: MissionTemplate) -> int:
    extra = get_mission_extra_attempts(manor, mission)
    return mission.daily_limit + extra


def mission_attempts_today(manor: Manor, mission: MissionTemplate) -> int:
    start_of_day, end_of_day, _ = get_today_date_range()
    return manor.mission_runs.filter(mission=mission, started_at__gte=start_of_day, started_at__lt=end_of_day).count()


def bulk_mission_attempts_today(manor: Manor, missions: List[MissionTemplate]) -> Dict[str, int]:
    from django.db.models import Count

    start_of_day, end_of_day, _ = get_today_date_range()
    counts = (
        manor.mission_runs.filter(started_at__gte=start_of_day, started_at__lt=end_of_day)
        .values("mission__key")
        .annotate(count=Count("id"))
    )
    result = {m.key: 0 for m in missions}
    for row in counts:
        key = row["mission__key"]
        if key in result:
            result[key] = row["count"]
    return result
