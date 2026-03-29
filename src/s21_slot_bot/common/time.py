from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError


def dt_to_isoz(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def dt_to_pretty(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def str_to_dt(text: str, tz: ZoneInfo) -> datetime:
    dt = TypeAdapter(datetime).validate_strings(text)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=tz)
    return dt


def str_to_dt_with_from(text: str, tz: ZoneInfo, from_dt: datetime) -> datetime:
    try:
        dt_to = str_to_dt(text, tz)
        return dt_to
    except ValidationError:
        delta = TypeAdapter(timedelta).validate_strings(text)
        dt_to = from_dt + delta
        return dt_to
