from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from s21_slot_bot.app.errors import InvalidUserInputError
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
            # time-only
            ("12:00", lambda now: now.replace(hour=12, minute=0, second=0, microsecond=0)),
            ("23:59", lambda now: now.replace(hour=23, minute=59, second=0, microsecond=0)),
            ("00:00", lambda now: now.replace(hour=0, minute=0, second=0, microsecond=0)),
            ("12:00:45", lambda now: now.replace(hour=12, minute=0, second=45, microsecond=0)),
            # over 23:59 is parsed as timedelta
            ("24:00", lambda now: now.replace(day=17)),
            # local datetime without timezone
            (
                "2026-08-17 12:00",
                lambda now: datetime(2026, 8, 17, 12, 0, tzinfo=now.tzinfo),
            ),
            (
                "2026-08-17T12:00:00",
                lambda now: datetime(2026, 8, 17, 12, 0, tzinfo=now.tzinfo),
            ),
            # datetime with explicit timezone
            (
                "2026-08-17T12:00:00+03:00",
                lambda now: datetime.fromisoformat("2026-08-17T12:00:00+03:00"),
            ),
            (
                "2026-08-17T09:00:00Z",
                lambda now: datetime.fromisoformat("2026-08-17T09:00:00+00:00"),
            ),
            # ISO 8601 durations
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
        expected_factory,
        now: datetime,
        logger_mock: MagicMock,
    ) -> None:
        expected = expected_factory(now)

        actual = parse_to_datetime(
            text=text,
            tz=now.tzinfo,
            from_dt=now,
            logger=logger_mock,
        )

        assert actual == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "abc",
            "2026-99-99 12:00",
            "P",
            "PT",
            "2 hours",
            "tomorrow",
        ],
    )
    def test_parse_to_datetime_invalid(
        self,
        text: str,
        now: datetime,
        timezone: ZoneInfo,
        logger_mock: MagicMock,
    ) -> None:
        with pytest.raises(InvalidUserInputError):
            parse_to_datetime(
                text=text,
                tz=timezone,
                from_dt=now,
                logger=logger_mock,
            )

    def test_parse_time_uses_from_date(
        self,
        timezone: ZoneInfo,
        logger_mock: MagicMock,
    ) -> None:
        from_dt = datetime(2026, 8, 20, 18, 30, tzinfo=timezone)

        actual = parse_to_datetime(
            text="12:00",
            tz=timezone,
            from_dt=from_dt,
            logger=logger_mock,
        )

        assert actual == datetime(2026, 8, 20, 12, 0, tzinfo=timezone)

    def test_dt_to_isoz_converts_to_utc(self, now: datetime) -> None:
        assert dt_to_isoz(now) == "2026-08-16T15:30:15.000Z"

    def test_dt_to_pretty_without_timezone_conversion(self, now: datetime) -> None:
        assert dt_to_pretty(now) == "2026-08-16 18:30:15"

    def test_dt_to_pretty_converts_timezone(self, now: datetime, timezone: ZoneInfo) -> None:
        utc_now = now.replace(tzinfo=UTC)

        assert dt_to_pretty(utc_now, timezone) == "2026-08-16 21:30:15"

    def test_dt_to_pretty_time_converts_timezone(self, now: datetime, timezone: ZoneInfo) -> None:
        utc_now = now.replace(tzinfo=UTC)

        assert dt_to_pretty_time(utc_now, timezone) == "21:30"

    def test_dt_to_markdown_contains_unix_timestamp_and_display_time(self, now: datetime) -> None:
        result = dt_to_markdown(now)

        assert result == rf"![2026\-08\-16 18:30:15](tg://time?unix={int(now.timestamp())})"

    def test_safe_isoz_to_dt_returns_none_for_none(self, timezone: ZoneInfo, logger_mock: MagicMock) -> None:
        assert safe_isoz_to_dt(None, timezone, logger_mock) is None
        logger_mock.warning.assert_not_called()

    def test_safe_isoz_to_dt_parses_datetime(self, timezone: ZoneInfo, logger_mock: MagicMock) -> None:
        result = safe_isoz_to_dt("2026-08-16T15:30:15.000Z", timezone, logger_mock)

        assert result == datetime(2026, 8, 16, 15, 30, 15, tzinfo=UTC)

    def test_safe_isoz_to_dt_returns_none_and_logs_warning_for_invalid_value(
        self,
        timezone: ZoneInfo,
        logger_mock: MagicMock,
    ) -> None:
        assert safe_isoz_to_dt("not-a-date", timezone, logger_mock) is None
        logger_mock.warning.assert_called_once()
