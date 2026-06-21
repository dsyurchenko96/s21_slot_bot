from datetime import date, datetime, timedelta, tzinfo
from datetime import time as dt_time
from typing import Callable

import pydantic
from pydantic import AwareDatetime, TypeAdapter

from s21_slot_bot.common.exceptions import InvalidUserInputError
from s21_slot_bot.common.logger import LoggerLike

type Parser = Callable[[str], datetime]

DateAdapter = TypeAdapter(date)
TimeAdapter = TypeAdapter(dt_time)
DatetimeAdapter = TypeAdapter(datetime)
TimedeltaAdapter = TypeAdapter(timedelta)


def dt_to_isoz(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def dt_to_pretty(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_to_datetime(text: str, tz: tzinfo, from_dt: AwareDatetime, logger: LoggerLike) -> datetime:
    parsers: list[tuple[str, Parser]] = [
        ("time", lambda value: _parse_as_time(value, tz)),
        ("date", lambda value: _parse_as_date(value, tz)),
        ("datetime", lambda value: _parse_as_datetime(value, tz)),
        ("timedelta", lambda value: _parse_as_timedelta(value, from_dt)),
    ]
    return _parse_with_chain(text, parsers, logger)


def _parse_as_time(text: str, tz: tzinfo) -> datetime:
    parsed_time = TimeAdapter.validate_strings(text)
    now = datetime.now(tz=tz)
    combined_dt = datetime.combine(now.date(), parsed_time, tzinfo=tz)
    return combined_dt


def _parse_as_date(text: str, tz: tzinfo) -> datetime:
    parsed_date = DateAdapter.validate_strings(text)
    combined_dt = datetime.combine(parsed_date, datetime.min.time(), tzinfo=tz)
    return combined_dt


def _parse_as_datetime(text: str, tz: tzinfo) -> datetime:
    parsed_dt = DatetimeAdapter.validate_strings(text)
    if not parsed_dt.tzinfo:
        parsed_dt = parsed_dt.replace(tzinfo=tz)
    return parsed_dt


def _parse_as_timedelta(text: str, from_dt: AwareDatetime) -> datetime:
    delta = TimedeltaAdapter.validate_strings(text)
    return from_dt + delta


def _parse_with_chain(
    text: str,
    parsers: list[tuple[str, Parser]],
    logger: LoggerLike,
) -> datetime:
    errors: list[Exception] = []

    for parser_name, parser in parsers:
        try:
            return parser(text)
        except pydantic.ValidationError as e:
            errors.append(e)

    logger.error(
        "Failed to parse user input `%s` as any supported time format: %s",
        text,
        ", ".join(name for name, _ in parsers),
        exc_info=errors[-1] if errors else None,
    )
    raise InvalidUserInputError("неподдерживаемый формат времени") from (errors[-1] if errors else None)
