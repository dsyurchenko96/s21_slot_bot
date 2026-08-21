from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from telegram.ext import Application, Job, JobQueue

from s21_slot_bot.app.booking_manager import BookingManager, is_expired_booking
from s21_slot_bot.app.errors import AppNotInitializedError, BookingRefresherError
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle
from s21_slot_bot.client.errors import School21Error, School21NoPointsError, School21SlotNotFoundError
from s21_slot_bot.client.models import Booking, DryBooking
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LoggerLike


class TestBookingManager:
    async def test_start_and_stop_refreshing(
        self,
        booking_manager: BookingManager,
        tg_app_mock: Application,
        job_queue_mock: JobQueue,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        job_queue_mock.run_repeating.return_value = job_mock
        await booking_manager.start_refreshing(logger_mock)
        assert booking_manager.state == Lifecycle.RUNNING
        assert booking_manager.is_refreshing
        job_mock.run.assert_awaited_once_with(tg_app_mock)

        await booking_manager.start_refreshing(logger_mock)
        job_queue_mock.run_repeating.assert_called_once()

        booking_manager.stop_refreshing(logger_mock)
        assert booking_manager.state == Lifecycle.STOPPED
        assert not booking_manager.is_refreshing

        booking_manager.stop_refreshing(logger_mock, state=Lifecycle.FAILED)
        assert booking_manager.state == Lifecycle.FAILED

    async def test_start_refreshing_requires_job_queue(
        self,
        booking_manager: BookingManager,
        tg_app_mock: Application,
        logger_mock: LoggerLike,
    ) -> None:
        tg_app_mock.job_queue = None
        with pytest.raises(AppNotInitializedError):
            await booking_manager.start_refreshing(logger_mock)

    async def test_refresh_now_only_runs_when_enabled(
        self,
        booking_manager: BookingManager,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        booking_manager._refresh_bookings = AsyncMock()
        await booking_manager.refresh_now(context, logger_mock)
        booking_manager._refresh_bookings.assert_not_awaited()

        booking_manager._state = Lifecycle.RUNNING
        await booking_manager.refresh_now(context, logger_mock)
        booking_manager._refresh_bookings.assert_awaited_once_with(context)

    async def test_book_dry_and_pop(
        self,
        booking_manager: BookingManager,
        messenger: Messenger,
        bot_instance_factory: Callable[..., BotInstance],
        context: CustomContext,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        messenger.send = AsyncMock()
        await booking_manager.book_dry(inst, "answer", now, context, is_staff_slot=True)
        assert inst.stats.attempts_success == 1
        dry = next(iter(booking_manager.dry_bookings.values()))
        assert dry.is_staff_slot is True
        assert booking_manager.pop_dry(dry.dry_run_id) == dry
        assert booking_manager.pop_dry(dry.dry_run_id) is None

    async def test_book_success(
        self,
        booking_manager: BookingManager,
        s21_client: School21Client,
        messenger: Messenger,
        bot_instance_factory: Callable[..., BotInstance],
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        s21_client.book = AsyncMock(return_value="booking-1")
        messenger.send = AsyncMock()
        assert await booking_manager.book(inst, "answer-1", now, logger_mock, context) is True
        assert inst.stats.currently_booked == 1
        assert inst.stats.attempts_success == 1
        assert "booking-1" in booking_manager.bookings

    async def test_book_no_points(
        self,
        booking_manager: BookingManager,
        s21_client: School21Client,
        messenger: Messenger,
        bot_instance_factory: Callable[..., BotInstance],
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        s21_client.book = AsyncMock(side_effect=School21NoPointsError("no points"))
        messenger.send = AsyncMock()
        assert await booking_manager.book(inst, "answer", now, logger_mock, context) is False

    @pytest.mark.parametrize("with_location", [True, False])
    async def test_book_slot_not_found(
        self,
        booking_manager: BookingManager,
        s21_client: School21Client,
        messenger: Messenger,
        bot_instance_factory: Callable[..., BotInstance],
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
        with_location: bool,
    ) -> None:
        inst = bot_instance_factory()
        location = {"input": {"startTime": "2026-08-19T17:30:00.000Z"}} if with_location else None
        s21_client.book = AsyncMock(side_effect=School21SlotNotFoundError("gone", location=location))
        messenger.send = AsyncMock()
        assert await booking_manager.book(inst, "answer", now, logger_mock, context) is True
        assert inst.stats.attempts_failed == 1
        messenger.send.assert_awaited_once()

    def test_remove_expired_dry_bookings(
        self,
        booking_manager: BookingManager,
        now: datetime,
    ) -> None:
        booking_manager._dry_bookings = {
            "expired": DryBooking(dry_run_id="expired", answer_id="a", project_id="p", project_name="P", start=now),
            "future": DryBooking(
                dry_run_id="future", answer_id="a", project_id="p", project_name="P", start=now + timedelta(hours=1)
            ),
        }
        booking_manager._remove_expired_dry_bookings(now)
        assert set(booking_manager.dry_bookings) == {"future"}

    def test_get_cancelled_bookings(
        self,
        booking_manager: BookingManager,
        booking_factory: Callable[..., Booking],
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        expired = booking_factory(booking_id="expired", start=now)
        cancelled = booking_factory(booking_id="cancelled", start=now + timedelta(hours=1))
        booking_manager._notifications_sent = {"expired": True, "cancelled": True}
        result = booking_manager._get_cancelled_bookings(
            {}, {"expired": expired, "cancelled": cancelled}, now, logger_mock
        )
        assert result == [cancelled]
        assert not booking_manager._notifications_sent

    @pytest.mark.parametrize("with_url", [True, False])
    async def test_notify_upcoming_review(
        self,
        booking_manager: BookingManager,
        messenger: Messenger,
        booking_factory: Callable[..., Booking],
        context: CustomContext,
        logger_mock: LoggerLike,
        with_url: bool,
    ) -> None:
        booking = booking_factory(url="https://call" if with_url else None)
        messenger.send = AsyncMock()
        await booking_manager._notify_on_upcoming_review(booking, context, logger_mock)
        text = messenger.send.await_args.args[1]
        assert ("ссылка для подключения" in text) is with_url
        assert booking_manager._notifications_sent[booking.id] is True

    async def test_notify_cancelled_reviews(
        self,
        booking_manager: BookingManager,
        messenger: Messenger,
        booking_factory: Callable[..., Booking],
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        messenger.send = AsyncMock()
        await booking_manager._notify_on_cancelled_reviews([], context, logger_mock)
        messenger.send.assert_not_awaited()

        bookings = [
            booking_factory(booking_id="1", project_name="P", start=now + timedelta(hours=1)),
            booking_factory(booking_id="2", project_name="P", start=now + timedelta(hours=2)),
        ]
        await booking_manager._notify_on_cancelled_reviews(bookings, context, logger_mock)
        assert "проверки отменены" in messenger.send.await_args.args[1]
        assert "слоты на" in messenger.send.await_args.args[1]

    async def test_refresh_bookings(
        self,
        booking_manager: BookingManager,
        s21_client: School21Client,
        messenger: Messenger,
        booking_factory: Callable[..., Booking],
        context: CustomContext,
        now: datetime,
    ) -> None:
        stale = booking_factory(booking_id="stale", start=now + timedelta(hours=2))
        upcoming = booking_factory(booking_id="upcoming", start=now + timedelta(minutes=10))
        booking_manager._bookings = {"stale": stale}
        s21_client.get_bookings = AsyncMock(return_value={"upcoming": upcoming})
        messenger.send = AsyncMock()
        with patch("s21_slot_bot.app.booking_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await booking_manager._refresh_bookings(context)
        assert booking_manager.bookings == {"upcoming": upcoming}
        assert context.ensured_chat_data.last_booking_refresh_time == now
        assert booking_manager._notifications_sent["upcoming"] is True
        assert messenger.send.await_count == 2  # cancellation + upcoming reminder

    async def test_refresh_failure(
        self,
        booking_manager: BookingManager,
        s21_client: School21Client,
        context: CustomContext,
        job_mock: Job,
    ) -> None:
        booking_manager._job = job_mock
        booking_manager._state = Lifecycle.RUNNING
        s21_client.get_bookings = AsyncMock(side_effect=School21Error("oops"))
        with pytest.raises(BookingRefresherError):
            await booking_manager._refresh_bookings(context)
        assert booking_manager.state == Lifecycle.FAILED
        assert not booking_manager.is_refreshing

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [(-1, True), (0, True), (1, False)],
    )
    def test_is_expired_booking(
        self,
        booking_factory: Callable[..., Booking],
        now: datetime,
        offset: int,
        expected: bool,
    ) -> None:
        assert is_expired_booking(booking_factory(start=now + timedelta(seconds=offset)), now) is expected
