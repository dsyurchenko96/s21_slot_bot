from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import Job, JobQueue

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import BotNotFoundError, BotRuntimeError, InternalError, TooManyBotsError
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle, Mode
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import LoggerLike


class TestBotManager:
    def test_check_bot_limits_raises_at_limit(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        bot_manager._bot_config.max_bots = 2
        bot_manager._bots = {
            "1": bot_instance_factory(bot_id="1"),
            "2": bot_instance_factory(bot_id="2"),
        }

        with pytest.raises(TooManyBotsError):
            bot_manager.check_bot_limits()

    def test_get_bot(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        inst = bot_instance_factory()
        bot_manager._bots[inst.cfg.bot_id] = inst

        assert bot_manager.get_bot(inst.cfg.bot_id) is inst

        with pytest.raises(BotNotFoundError):
            bot_manager.get_bot("missing")

    def test_list_all_filters_and_orders(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
    ) -> None:
        stopped = bot_instance_factory(
            bot_id="b",
            project_id="2",
            state=Lifecycle.STOPPED,
        )
        failed = bot_instance_factory(
            bot_id="c",
            project_id="1",
            state=Lifecycle.FAILED,
        )
        running_2 = bot_instance_factory(
            bot_id="b",
            project_id="1",
            state=Lifecycle.RUNNING,
        )
        running_1 = bot_instance_factory(
            bot_id="a",
            project_id="1",
            state=Lifecycle.RUNNING,
        )
        bot_manager._bots = {
            "stopped": stopped,
            "failed": failed,
            "running-2": running_2,
            "running-1": running_1,
        }

        assert bot_manager.list_all() == [running_1, running_2, stopped, failed]
        assert bot_manager.list_all(states={Lifecycle.FAILED}) == [failed]

    async def test_start_bot_registers_and_runs_search(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        booking_manager_mock: BookingManager,
        context: CustomContext,
        job_queue_mock: JobQueue,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        inst = bot_instance_factory()
        s21_client_mock.get_task_and_answer = AsyncMock(return_value=("task-1", "answer-1"))
        job_queue_mock.run_repeating.return_value = job_mock

        await bot_manager.start_bot(inst, context, logger_mock)

        assert inst.state == Lifecycle.RUNNING
        assert bot_manager.get_bot(inst.cfg.bot_id) is inst
        booking_manager_mock.start_refreshing.assert_awaited_once_with(logger_mock)
        job_mock.run.assert_awaited_once_with(context.application)

    async def test_start_bot_wraps_client_failure(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        inst = bot_instance_factory()
        s21_client_mock.get_task_and_answer = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(BotRuntimeError, match="не удалось получить"):
            await bot_manager.start_bot(inst, context, logger_mock)

        assert bot_manager.list_all() == []

    def test_stop_bot_stops_job_and_last_booking_refresher(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        booking_manager_mock: BookingManager,
        context: CustomContext,
        job_queue_mock: JobQueue,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.RUNNING)
        bot_manager._bots[inst.cfg.bot_id] = inst
        bot_manager._bot_config.should_refresh_bookings_on_active_bots = True
        job_queue_mock.get_jobs_by_name.return_value = [job_mock]

        result = bot_manager.stop_bot(inst.cfg.bot_id, context, logger_mock)

        assert result is True
        assert inst.state == Lifecycle.STOPPED
        job_mock.schedule_removal.assert_called_once()
        booking_manager_mock.stop_refreshing.assert_called_once_with(logger_mock)

    def test_stop_bot_does_not_stop_refresher_when_another_bot_is_running(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        booking_manager_mock: BookingManager,
        context: CustomContext,
        job_queue_mock: JobQueue,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        first = bot_instance_factory(bot_id="first", state=Lifecycle.RUNNING)
        second = bot_instance_factory(bot_id="second", state=Lifecycle.RUNNING)
        bot_manager._bots = {"first": first, "second": second}
        bot_manager._bot_config.should_refresh_bookings_on_active_bots = True
        job_queue_mock.get_jobs_by_name.return_value = [job_mock]

        assert bot_manager.stop_bot("first", context, logger_mock) is True

        booking_manager_mock.stop_refreshing.assert_not_called()

    def test_delete_bot_removes_bot(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        context: CustomContext,
        job_queue_mock: JobQueue,
        job_mock: Job,
        logger_mock: LoggerLike,
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.RUNNING)
        bot_manager._bots[inst.cfg.bot_id] = inst
        job_queue_mock.get_jobs_by_name.return_value = [job_mock]

        assert bot_manager.delete_bot(inst.cfg.bot_id, context, logger_mock) is True

        with pytest.raises(BotNotFoundError):
            bot_manager.get_bot(inst.cfg.bot_id)

    async def test_search_requires_job(
        self,
        bot_manager: BotManager,
        context: CustomContext,
    ) -> None:
        context.job = None

        with pytest.raises(InternalError):
            await bot_manager._search(context)

    async def test_search_deletes_expired_bot(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        messenger_mock: Messenger,
        context: CustomContext,
        job_mock: Job,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory(
            state=Lifecycle.RUNNING,
            to_dt=now,
        )
        bot_manager._bots[inst.cfg.bot_id] = inst
        job_mock.data = {
            "inst": inst,
            "task_id": "task-1",
            "answer_id": "answer-1",
        }
        job_mock.name = inst.cfg.bot_id
        context.job = job_mock
        bot_manager.delete_bot = MagicMock(return_value=True)

        with patch("s21_slot_bot.app.bot_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await bot_manager._search(context)

        bot_manager.delete_bot.assert_called_once()
        messenger_mock.send.assert_awaited_once()

    async def test_search_does_nothing_when_enough_reviews_are_booked(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        booking_manager_mock: BookingManager,
        context: CustomContext,
        job_mock: Job,
        slots_info_factory,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory(
            state=Lifecycle.RUNNING,
            required_reviews=2,
            to_dt=now + timedelta(hours=1),
        )
        job_mock.data = {
            "inst": inst,
            "task_id": "task-1",
            "answer_id": "answer-1",
        }
        job_mock.name = inst.cfg.bot_id
        context.job = job_mock
        s21_client_mock.get_slots_info = AsyncMock(return_value=slots_info_factory(booked=2, required=2))

        with patch("s21_slot_bot.app.bot_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await bot_manager._search(context)

        assert inst.stats.currently_booked == 2
        booking_manager_mock.book.assert_not_awaited()
        booking_manager_mock.book_dry.assert_not_awaited()

    async def test_search_only_find_books_dry_and_stops(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        booking_manager_mock: BookingManager,
        context: CustomContext,
        job_mock: Job,
        slots_info_factory,
        timeslot_factory,
        now: datetime,
    ) -> None:
        start = now + timedelta(minutes=20)
        inst = bot_instance_factory(
            state=Lifecycle.RUNNING,
            mode=Mode.ONLY_FIND,
            to_dt=now + timedelta(hours=1),
        )
        job_mock.data = {
            "inst": inst,
            "task_id": "task-1",
            "answer_id": "answer-1",
        }
        job_mock.name = inst.cfg.bot_id
        context.job = job_mock
        s21_client_mock.get_slots_info = AsyncMock(
            return_value=slots_info_factory(
                booked=0,
                time_slots=[timeslot_factory(valid_start_times=[start], staff_slot=True)],
            )
        )
        bot_manager.stop_bot = MagicMock(return_value=True)

        with patch("s21_slot_bot.app.bot_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await bot_manager._search(context)

        booking_manager_mock.book_dry.assert_awaited_once_with(
            inst=inst,
            answer_id="answer-1",
            start_time=start,
            context=context,
            is_staff_slot=True,
        )
        bot_manager.stop_bot.assert_called_once()

    async def test_search_find_and_book_stops_when_no_points_left(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        booking_manager_mock: BookingManager,
        context: CustomContext,
        job_mock: Job,
        slots_info_factory,
        timeslot_factory,
        now: datetime,
    ) -> None:
        start = now + timedelta(minutes=20)
        inst = bot_instance_factory(
            state=Lifecycle.RUNNING,
            mode=Mode.FIND_AND_BOOK,
            to_dt=now + timedelta(hours=1),
        )
        job_mock.data = {
            "inst": inst,
            "task_id": "task-1",
            "answer_id": "answer-1",
        }
        job_mock.name = inst.cfg.bot_id
        context.job = job_mock
        s21_client_mock.get_slots_info = AsyncMock(
            return_value=slots_info_factory(
                booked=0,
                time_slots=[timeslot_factory(valid_start_times=[start])],
            )
        )
        booking_manager_mock.book = AsyncMock(return_value=False)
        bot_manager.stop_bot = MagicMock(return_value=True)

        with patch("s21_slot_bot.app.bot_manager.datetime") as datetime_mock:
            datetime_mock.now.return_value = now
            await bot_manager._search(context)

        booking_manager_mock.book.assert_awaited_once()
        bot_manager.stop_bot.assert_called_once()

    async def test_search_wraps_failure_and_increments_failed_attempts(
        self,
        bot_manager: BotManager,
        bot_instance_factory: Callable[..., BotInstance],
        s21_client_mock: School21Client,
        context: CustomContext,
        job_mock: Job,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory(
            state=Lifecycle.RUNNING,
            to_dt=now + timedelta(hours=1),
        )
        job_mock.data = {
            "inst": inst,
            "task_id": "task-1",
            "answer_id": "answer-1",
        }
        job_mock.name = inst.cfg.bot_id
        context.job = job_mock
        s21_client_mock.get_slots_info = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("s21_slot_bot.app.bot_manager.datetime") as datetime_mock,
            pytest.raises(BotRuntimeError, match="ошибка поиска"),
        ):
            datetime_mock.now.return_value = now
            await bot_manager._search(context)

        assert inst.stats.attempts_failed == 1

    @pytest.mark.parametrize(
        ("slots", "expected_time", "expected_staff"),
        [
            ([], None, None),
            (
                [
                    ("2026-08-16T19:00:00+03:00", False),
                    ("2026-08-16T18:45:00+03:00", True),
                ],
                datetime.fromisoformat("2026-08-16T18:45:00+03:00"),
                True,
            ),
        ],
    )
    def test_pick_candidate_start(
        self,
        bot_manager: BotManager,
        timeslot_factory,
        slots,
        expected_time,
        expected_staff,
    ) -> None:
        if not slots:
            timeslots = []
        else:
            timeslots = [
                timeslot_factory(
                    valid_start_times=[datetime.fromisoformat(time)],
                    staff_slot=staff,
                )
                for time, staff in slots
            ]

        actual = bot_manager._pick_candidate_start(timeslots)

        if expected_time is None:
            assert actual is None
        else:
            assert actual == (expected_time, expected_staff)
