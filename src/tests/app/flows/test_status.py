from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from telegram import CallbackQuery, Update

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import BookingRefresherError
from s21_slot_bot.app.flows.actions import StatusFlowAction
from s21_slot_bot.app.flows.status import StatusFlow
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotInstance, CustomContext, Lifecycle
from s21_slot_bot.client.models import Booking, DryBooking


class TestStatusFlow:
    async def test_status_refresh_renders_status(
        self,
        status_flow: StatusFlow,
        booking_manager_mock: BookingManager,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        booking_manager_mock.state = Lifecycle.RUNNING
        booking_manager_mock.bookings = {}
        booking_manager_mock.dry_bookings = {}
        bot_manager_mock.list_all.return_value = []
        bot_manager_mock.max_bots = 3
        bot_manager_mock.poll_interval_sec = 60

        await status_flow.status_refresh(update_mock, context)

        booking_manager_mock.refresh_now.assert_awaited_once()
        text = messenger_mock.render_menu_message.await_args.args[1]
        assert "📌 статус" in text
        assert "ботов нет" in text

    async def test_status_refresh_still_renders_when_booking_refresh_fails(
        self,
        status_flow: StatusFlow,
        booking_manager_mock: BookingManager,
        bot_manager_mock: BotManager,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        booking_manager_mock.refresh_now = AsyncMock(side_effect=BookingRefresherError("boom"))
        booking_manager_mock.state = Lifecycle.FAILED
        booking_manager_mock.bookings = {}
        booking_manager_mock.dry_bookings = {}
        bot_manager_mock.list_all.return_value = []
        bot_manager_mock.max_bots = 3
        bot_manager_mock.poll_interval_sec = 60

        await status_flow.status_refresh(update_mock, context)

        messenger_mock.render_menu_message.assert_awaited_once()

    async def test_start_booking_refresher_from_callback(
        self,
        status_flow: StatusFlow,
        booking_manager_mock: BookingManager,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        status_flow.status_refresh = AsyncMock()

        await status_flow.parse_callback(
            [StatusFlowAction.START_BOOKING_REFRESHER],
            query_mock,
            context,
        )

        booking_manager_mock.start_refreshing.assert_awaited_once()
        status_flow.status_refresh.assert_awaited_once_with(query_mock, context)

    async def test_stop_booking_refresher_from_callback(
        self,
        status_flow: StatusFlow,
        booking_manager_mock: BookingManager,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        status_flow.status_refresh = AsyncMock()

        await status_flow.parse_callback(
            [StatusFlowAction.STOP_BOOKING_REFRESHER],
            query_mock,
            context,
        )

        booking_manager_mock.stop_refreshing.assert_called_once()
        status_flow.status_refresh.assert_awaited_once_with(query_mock, context)

    def test_status_groups_bookings_and_bots_by_project(
        self,
        status_flow: StatusFlow,
        booking_manager_mock: BookingManager,
        bot_manager_mock: BotManager,
        context: CustomContext,
        bot_instance_factory: Callable[..., BotInstance],
        now: datetime,
    ) -> None:
        bot = bot_instance_factory(
            project_id="project-1",
            project_name="Project 1",
            state=Lifecycle.RUNNING,
        )
        bot_manager_mock.list_all.side_effect = lambda states=None: [bot]
        bot_manager_mock.max_bots = 3
        bot_manager_mock.poll_interval_sec = 60
        booking_manager_mock.state = Lifecycle.RUNNING
        booking_manager_mock.bookings = {
            "booking-1": Booking(
                id="booking-1",
                answer_id="answer-1",
                project_id="project-1",
                project_name="Project 1",
                start=now + timedelta(minutes=30),
            )
        }
        booking_manager_mock.dry_bookings = {
            "dry-1": DryBooking(
                dry_run_id="dry-1",
                answer_id="answer-1",
                project_id="project-1",
                project_name="Project 1",
                start=now + timedelta(minutes=45),
            )
        }

        text = "\n".join(status_flow._get_status_lines(context))

        assert "Project 1" in text
        assert "📝 запись" in text
        assert "🔍 найден слот" in text
        assert f"#{bot.cfg.bot_id}" in text
