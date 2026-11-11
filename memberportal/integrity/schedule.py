"""When the checks run and the digest goes out.

Both are in the site's time zone rather than Celery's (UTC unless
CELERY_TIMEZONE is set), so the check runs at night wherever the space is.
Celery beat and the admin page read the times from here, so they can't
disagree.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

DAILY_CHECK = {"hour": 3, "minute": 15}
WEEKLY_DIGEST = {"day_of_week": "mon", "hour": 8, "minute": 15}


def site_time_zone():
    return ZoneInfo(settings.TIME_ZONE)


def _clock(times):
    return f"{times['hour']:02d}:{times['minute']:02d}"


def next_daily_check(now=None):
    local = timezone.localtime(now or timezone.now(), site_time_zone())
    due = local.replace(
        hour=DAILY_CHECK["hour"],
        minute=DAILY_CHECK["minute"],
        second=0,
        microsecond=0,
    )
    if due <= local:
        due += timedelta(days=1)
    return due


def describe():
    return {
        "dailyCheckAt": _clock(DAILY_CHECK),
        "weeklyDigestDay": WEEKLY_DIGEST["day_of_week"],
        "weeklyDigestAt": _clock(WEEKLY_DIGEST),
        "timeZone": settings.TIME_ZONE,
    }
