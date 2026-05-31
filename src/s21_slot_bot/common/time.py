from datetime import datetime, timedelta, tzinfo

import pydantic
from pydantic import AwareDatetime, TypeAdapter

from s21_slot_bot.common.exceptions import InvalidUserInputError
from s21_slot_bot.common.logger import LoggerLike, LogLevel


def dt_to_isoz(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def dt_to_pretty(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def str_to_dt(text: str, tz: tzinfo, logger: LoggerLike, log_level: LogLevel = LogLevel.ERROR) -> datetime:
    try:
        dt = TypeAdapter(datetime).validate_strings(text)
    except pydantic.ValidationError as e:
        logger.log(
            log_level, f"Failed to parse user input `{text}` as datetime", exc_info=bool(log_level == LogLevel.ERROR)
        )
        raise InvalidUserInputError("неподдерживаемый формат времени") from e
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=tz)
    return dt


def str_to_dt_with_from(text: str, tz: tzinfo, from_dt: AwareDatetime, logger: LoggerLike) -> datetime:
    try:
        dt_to = str_to_dt(text, tz, logger, log_level=LogLevel.INFO)
        return dt_to
    except InvalidUserInputError:
        pass
    try:
        delta = TypeAdapter(timedelta).validate_strings(text)
        dt_to = from_dt + delta
        return dt_to
    except pydantic.ValidationError as e:
        logger.error(f"Failed to parse user input `{text}` as timedelta")
        raise InvalidUserInputError("неподдерживаемый формат времени") from e
