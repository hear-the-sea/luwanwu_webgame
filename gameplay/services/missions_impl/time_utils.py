from __future__ import annotations

from datetime import timedelta

from django.utils import timezone


def get_today_date_range():
    """Return (start_of_day, end_of_day, today_date) in server timezone."""
    now = timezone.now()
    tz = timezone.get_current_timezone()
    start_of_day = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    today_date = start_of_day.date()
    return start_of_day, end_of_day, today_date
