"""
The API's date/time wire format.

Every point in time the API sends to a client is an ISO 8601 string in UTC
with millisecond precision and a trailing "Z", e.g. "2026-09-24T08:15:00.000Z".
It's the same shape JavaScript's Date.prototype.toISOString() produces, so the
frontend can parse it unambiguously and show it in the viewer's local time.
Calendar dates with no time component (datetime.date) are sent as "YYYY-MM-DD".

Views can return datetime objects as-is: UTCJSONRenderer (the default DRF
renderer, see settings.REST_FRAMEWORK) formats them. Use to_utc_iso() directly
when building a string outside a DRF response, and from_unix() for Unix
timestamps (e.g. from Stripe) so they go out in the same format.
"""

import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.formats import date_format
from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder


def to_utc_iso(value):
    """Formats a datetime as an ISO 8601 UTC string. None passes through."""
    if value is None:
        return None
    if timezone.is_naive(value):
        # Naive datetimes are wall-clock time in settings.TIME_ZONE.
        value = timezone.make_aware(value)
    return (
        value.astimezone(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def from_unix(timestamp):
    """Converts a Unix timestamp to an aware UTC datetime. None passes through."""
    if timestamp is None:
        return None
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)


def parse_client_datetime(value):
    """
    Parses an ISO 8601 datetime sent by a client. A value without an offset is
    taken as wall-clock time in settings.TIME_ZONE. Raises ValueError if the
    value isn't a valid datetime.
    """
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime: {value!r}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def format_local_datetime(value):
    """Human-readable datetime in settings.TIME_ZONE, for emails and messages."""
    return date_format(timezone.localtime(value), "DATETIME_FORMAT")


class UTCJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return to_utc_iso(obj)
        return super().default(obj)


class UTCJSONRenderer(JSONRenderer):
    encoder_class = UTCJSONEncoder
