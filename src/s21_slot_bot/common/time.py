from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter


def dt_to_isoz(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def dt_to_pretty(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def str_to_dt(text: str, tz: ZoneInfo) -> datetime:
    dt = TypeAdapter(datetime).validate_python(text)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=tz)
    return dt
