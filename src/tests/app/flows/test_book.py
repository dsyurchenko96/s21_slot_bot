from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from telegram import CallbackQuery

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import BotRuntimeError
from s21_slot_bot.app.flows.actions import BookFlowAction
from s21_slot_bot.app.flows.book import BookFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import CustomContext, Lifecycle
from s21_slot_bot.client.errors import School21Error
from s21_slot_bot.client.models import DryBooking


class TestBookFlow:
    async def test_manual_booking_success(
        self,
        book_flow: BookFlow,
        bot_manager_mock: BotManager,
        booking_manager_mock: BookingManager,
        messenger_mock: Messenger,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.RUNNING)
        dry = DryBooking(
            dry_run_id="dry-1",
            answer_id="answer-1",
            project_id=inst.cfg.project_id,
            project_name=inst.cfg.project_name,
            start=now,
            is_staff_slot=False,
        )
        bot_manager_mock.get_bot.return_value = inst
        booking_manager_mock.pop_dry.return_value = dry
        booking_manager_mock.book = AsyncMock(return_value=True)

        await book_flow.parse_callback(
            ["dry-1", inst.cfg.bot_id, BookFlowAction.BOOK_ATTEMPT_MANUAL],
            query_mock,
            context,
        )

        assert inst.stats.attempts_total == 1
        booking_manager_mock.book.assert_awaited_once()
        bot_manager_mock.stop_bot.assert_not_called()
        messenger_mock.safe_delete.assert_awaited_once()

    async def test_manual_booking_stops_bot_when_no_points_left(
        self,
        book_flow: BookFlow,
        bot_manager_mock: BotManager,
        booking_manager_mock: BookingManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory(state=Lifecycle.RUNNING)
        dry = DryBooking(
            dry_run_id="dry-1",
            answer_id="answer-1",
            project_id=inst.cfg.project_id,
            project_name=inst.cfg.project_name,
            start=now,
        )
        bot_manager_mock.get_bot.return_value = inst
        booking_manager_mock.pop_dry.return_value = dry
        booking_manager_mock.book = AsyncMock(return_value=False)

        await book_flow.parse_callback(
            ["dry-1", inst.cfg.bot_id, BookFlowAction.BOOK_ATTEMPT_MANUAL],
            query_mock,
            context,
        )

        bot_manager_mock.stop_bot.assert_called_once()

    async def test_manual_booking_requires_saved_dry_booking(
        self,
        book_flow: BookFlow,
        bot_manager_mock: BotManager,
        booking_manager_mock: BookingManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory,
    ) -> None:
        inst = bot_instance_factory()
        bot_manager_mock.get_bot.return_value = inst
        booking_manager_mock.pop_dry.return_value = None

        with pytest.raises(BotRuntimeError, match="не удалось найти сохраненную запись"):
            await book_flow.parse_callback(
                ["dry-1", inst.cfg.bot_id, BookFlowAction.BOOK_ATTEMPT_MANUAL],
                query_mock,
                context,
            )

    async def test_manual_booking_wraps_school21_error(
        self,
        book_flow: BookFlow,
        bot_manager_mock: BotManager,
        booking_manager_mock: BookingManager,
        query_mock: CallbackQuery,
        context: CustomContext,
        bot_instance_factory,
        now: datetime,
    ) -> None:
        inst = bot_instance_factory()
        dry = DryBooking(
            dry_run_id="dry-1",
            answer_id="answer-1",
            project_id=inst.cfg.project_id,
            project_name=inst.cfg.project_name,
            start=now,
        )
        bot_manager_mock.get_bot.return_value = inst
        booking_manager_mock.pop_dry.return_value = dry
        booking_manager_mock.book = AsyncMock(side_effect=School21Error("backend"))

        with pytest.raises(BotRuntimeError, match="не удалось записаться"):
            await book_flow.parse_callback(
                ["dry-1", inst.cfg.bot_id, BookFlowAction.BOOK_ATTEMPT_MANUAL],
                query_mock,
                context,
            )
