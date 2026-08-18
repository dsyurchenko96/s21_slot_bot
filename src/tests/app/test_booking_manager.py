from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import Application, Job, JobQueue

from s21_slot_bot.app.booking_manager import BookingManager, is_expired_booking
from s21_slot_bot.app.errors import AppNotInitializedError, BookingRefresherError
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle
from s21_slot_bot.client.errors import School21NoPointsError, School21SlotNotFoundError
from s21_slot_bot.client.models import Booking, DryBooking
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LoggerLike


class TestBookingManager:
    async def test_start_refreshing_schedules_and_runs_immediately(
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

    async def test_start_refreshing_does_not_duplicate_existing_job(
        self,
        booking_manager: BookingManager,
        job_queue_mock: JobQueue,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        job_queue_mock.run_repeating.return_value = job_mock
        await booking_manager.start_refreshing(logger_mock, run_immediately=False)

        await booking_manager.start_refreshing(logger_mock)

        job_queue_mock.run_repeating.assert_called_once()

    async def test_start_refreshing_requires_job_queue(
        self,
        booking_manager: BookingManager,
        tg_app_mock: Application,
        logger_mock: LoggerLike,
    ) -> None:
        tg_app_mock.job_queue = None

        with pytest.raises(AppNotInitializedError):
            await booking_manager.start_refreshing(logger_mock)

    def test_stop_refreshing_removes_job_and_updates_state(
        self,
        booking_manager: BookingManager,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        booking_manager._job = job_mock
        booking_manager._state = Lifecycle.RUNNING

        booking_manager.stop_refreshing(logger_mock, state=Lifecycle.FAILED)

        assert booking_manager.state == Lifecycle.FAILED
        assert not booking_manager.is_refreshing
        job_mock.schedule_removal.assert_called_once()

    async def test_refresh_now_only_refreshes_when_running(
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

    async def test_book_success_updates_state_and_notifies(
        self,
        booking_manager: BookingManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        start = now + timedelta(minutes=30)
        s21_client_mock.book = AsyncMock(return_value="booking-1")

        result = await booking_manager.book(
            inst=inst,
            answer_id="answer-1",
            start_time=start,
            logger=logger_mock,
            context=context,
        )

        assert result is True
        assert inst.stats.currently_booked == 1
        assert inst.stats.attempts_success == 1
        assert booking_manager.bookings["booking-1"].start == start
        messenger_mock.send.assert_awaited_once()

    async def test_book_returns_false_when_no_p2p_points(
        self,
        booking_manager: BookingManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        s21_client_mock.book = AsyncMock(side_effect=School21NoPointsError("no points"))

        result = await booking_manager.book(
            inst=inst,
            answer_id="answer-1",
            start_time=now + timedelta(minutes=30),
            logger=logger_mock,
            context=context,
        )

        assert result is False
        assert inst.stats.attempts_success == 0
        assert not booking_manager.bookings
        messenger_mock.send.assert_awaited_once()

    async def test_book_handles_slot_not_found(
        self,
        booking_manager: BookingManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        s21_client_mock.book = AsyncMock(
            side_effect=School21SlotNotFoundError(
                "gone",
                location={"input": {"startTime": "2026-08-16T16:00:00.000Z"}},
            )
        )

        result = await booking_manager.book(
            inst=inst,
            answer_id="answer-1",
            start_time=now + timedelta(minutes=30),
            logger=logger_mock,
            context=context,
        )

        assert result is True
        assert inst.stats.attempts_failed == 1
        assert not booking_manager.bookings
        messenger_mock.send.assert_awaited_once()

    async def test_book_dry_stores_booking_and_notifies(
        self,
        booking_manager: BookingManager,
        bot_instance_factory: Callable[..., BotInstance],
        messenger_mock: Messenger,
        context: CustomContext,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        start = now + timedelta(minutes=30)

        await booking_manager.book_dry(
            inst=inst,
            answer_id="answer-1",
            start_time=start,
            context=context,
            is_staff_slot=True,
        )

        assert inst.stats.attempts_success == 1
        assert len(booking_manager.dry_bookings) == 1
        dry = next(iter(booking_manager.dry_bookings.values()))
        assert dry.start == start
        assert dry.is_staff_slot is True
        messenger_mock.send.assert_awaited_once()

    def test_pop_dry_removes_and_returns_booking(
        self,
        booking_manager: BookingManager,
        now: datetime,
    ) -> None:
        dry = DryBooking(
            dry_run_id="dry-1",
            answer_id="answer-1",
            project_id="project-1",
            project_name="Project",
            start=now + timedelta(minutes=10),
        )
        booking_manager._dry_bookings[dry.dry_run_id] = dry

        assert booking_manager.pop_dry("dry-1") == dry
        assert booking_manager.pop_dry("dry-1") is None

    async def test_refresh_bookings_replaces_state_and_records_refresh_time(
        self,
        booking_manager: BookingManager,
        booking_factory: Callable[..., Booking],
        s21_client_mock: School21Client,
        context: CustomContext,
        now: datetime,
    ) -> None:
        fresh = booking_factory(booking_id="fresh")
        s21_client_mock.get_bookings = AsyncMock(return_value={"fresh": fresh})
        booking_manager._notify_on_cancelled_reviews = AsyncMock()
        booking_manager._notify_on_upcoming_review = AsyncMock()

        with patch("s21_slot_bot.app.booking_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await booking_manager._refresh_bookings(context)

        assert booking_manager.bookings == {"fresh": fresh}
        assert context.ensured_chat_data.last_booking_refresh_time == now

    async def test_refresh_bookings_notifies_cancelled_booking_once(
        self,
        booking_manager: BookingManager,
        booking_factory: Callable[..., Booking],
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        context: CustomContext,
        now: datetime,
    ) -> None:
        stale = booking_factory(booking_id="cancelled", start=now + timedelta(hours=1))
        booking_manager._bookings = {"cancelled": stale}
        s21_client_mock.get_bookings = AsyncMock(return_value={})

        with patch("s21_slot_bot.app.booking_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await booking_manager._refresh_bookings(context)

        messenger_mock.send.assert_awaited_once()

    async def test_refresh_bookings_sends_upcoming_notification_only_once(
        self,
        booking_manager: BookingManager,
        booking_factory: Callable[..., Booking],
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        context: CustomContext,
        now: datetime,
    ) -> None:
        upcoming = booking_factory(
            booking_id="upcoming",
            start=now + timedelta(minutes=10),
        )
        s21_client_mock.get_bookings = AsyncMock(return_value={"upcoming": upcoming})

        with patch("s21_slot_bot.app.booking_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await booking_manager._refresh_bookings(context)
            await booking_manager._refresh_bookings(context)

        assert messenger_mock.send.await_count == 1

    async def test_refresh_failure_stops_refresher_and_raises(
        self,
        booking_manager: BookingManager,
        s21_client_mock: School21Client,
        context: CustomContext,
    ) -> None:
        booking_manager._state = Lifecycle.RUNNING
        booking_manager._job = MagicMock()
        s21_client_mock.get_bookings = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(BookingRefresherError, match="boom"):
            await booking_manager._refresh_bookings(context)

        assert booking_manager.state == Lifecycle.FAILED
        assert not booking_manager.is_refreshing

    @pytest.mark.parametrize(
        ("offset_seconds", "expected"),
        [
            (-1, True),
            (0, True),
            (1, False),
        ],
    )
    def test_is_expired_booking_boundary(
        self,
        booking_factory: Callable[..., Booking],
        now: datetime,
        offset_seconds: int,
        expected: bool,
    ) -> None:
        booking = booking_factory(start=now + timedelta(seconds=offset_seconds))

        assert is_expired_booking(booking, now) is expected
