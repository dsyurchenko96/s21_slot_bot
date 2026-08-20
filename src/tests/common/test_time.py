from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from s21_slot_bot.app.errors import InvalidUserInputError
from s21_slot_bot.common.logger import LoggerLike
from s21_slot_bot.common.time import (
    dt_to_isoz,
    dt_to_markdown,
    dt_to_pretty,
    dt_to_pretty_time,
    parse_to_datetime,
    safe_isoz_to_dt,
)


class TestTime:
    @pytest.mark.parametrize(
        ("text", "expected_factory"),
        [
            ("12:00", lambda now: now.replace(hour=12, minute=0, second=0, microsecond=0)),
            ("23:59", lambda now: now.replace(hour=23, minute=59, second=0, microsecond=0)),
            ("00:00", lambda now: now.replace(hour=0, minute=0, second=0, microsecond=0)),
            ("24:00", lambda now: now + timedelta(days=1)),  # 24:00 and over is treated as timedelta
            ("12:00:45", lambda now: now.replace(hour=12, minute=0, second=45, microsecond=0)),
            ("2026-08-20", lambda now: datetime(2026, 8, 20, tzinfo=now.tzinfo)),
            ("2026-08-20 12:00", lambda now: datetime(2026, 8, 20, 12, 0, tzinfo=now.tzinfo)),
            ("2026-08-20T12:00:30", lambda now: datetime(2026, 8, 20, 12, 0, 30, tzinfo=now.tzinfo)),
            (
                "2026-08-20T12:00:00+03:00",
                lambda now: datetime.fromisoformat("2026-08-20T12:00:00+03:00"),
            ),
            (
                "2026-08-20T09:00:00Z",
                lambda now: datetime.fromisoformat("2026-08-20T09:00:00+00:00"),
            ),
            ("PT0S", lambda now: now),
            ("PT30M", lambda now: now + timedelta(minutes=30)),
            ("PT2H", lambda now: now + timedelta(hours=2)),
            ("PT1H30M", lambda now: now + timedelta(hours=1, minutes=30)),
            ("P1D", lambda now: now + timedelta(days=1)),
            ("P2DT3H", lambda now: now + timedelta(days=2, hours=3)),
            ("PT45S", lambda now: now + timedelta(seconds=45)),
        ],
    )
    def test_parse_to_datetime(
        self,
        text: str,
        expected_factory: Callable[[datetime], datetime],
        now: datetime,
        logger_mock: LoggerLike,
    ) -> None:
        assert parse_to_datetime(text, now.tzinfo, now, logger_mock) == expected_factory(now)

    @pytest.mark.parametrize(
        "text",
        ["", "abc", "2026-99-99 12:00", "P", "PT", "2 hours", "tomorrow"],
    )
    def test_parse_to_datetime_invalid(
        self,
        text: str,
        now: datetime,
        timezone: ZoneInfo,
        logger_mock: LoggerLike,
    ) -> None:
        with pytest.raises(InvalidUserInputError):
            parse_to_datetime(text, timezone, now, logger_mock)

    def test_dt_to_isoz(self, now: datetime) -> None:
        assert dt_to_isoz(now) == "2026-08-19T17:10:15.000Z"

    def test_pretty_helpers(self, now: datetime, timezone: ZoneInfo) -> None:
        assert dt_to_pretty(now) == "2026-08-19 20:10:15"
        assert dt_to_pretty_time(now) == "20:10"
        assert dt_to_pretty(now.astimezone(UTC), timezone) == "2026-08-19 20:10:15"

    def test_dt_to_markdown(self, now: datetime) -> None:
        assert dt_to_markdown(now) == rf"![2026\-08\-19 20:10:15](tg://time?unix={int(now.timestamp())})"

    def test_safe_isoz_to_dt(
        self,
        timezone: ZoneInfo,
        logger_mock: LoggerLike,
    ) -> None:
        assert safe_isoz_to_dt(None, timezone, logger_mock) is None
        assert safe_isoz_to_dt("2026-08-19T17:10:15.000Z", timezone, logger_mock) == datetime(
            2026, 8, 19, 17, 10, 15, tzinfo=UTC
        )
        assert safe_isoz_to_dt("not-a-date", timezone, logger_mock) is None
