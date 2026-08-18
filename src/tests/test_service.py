from telegram.ext import Application

from s21_slot_bot.app.booking_manager import BookingManager
from s21_slot_bot.app.input_handler import InputHandler
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import ChatData
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.config import SlotBotServiceConfig
from s21_slot_bot.service import SlotBotService


class TestSlotBotService:
    def test_wires_application_handlers(
        self,
        service: SlotBotService,
        tg_app_mock: Application,
        input_handler_mock: InputHandler,
    ) -> None:
        assert tg_app_mock.add_handler.call_count == 3
        tg_app_mock.add_error_handler.assert_called_once_with(input_handler_mock.on_error)
        assert tg_app_mock.post_init == service._post_init
        assert tg_app_mock.post_stop == service._post_stop

    def test_start_runs_polling(
        self,
        service: SlotBotService,
        tg_app_mock: Application,
    ) -> None:
        service.start()

        tg_app_mock.run_polling.assert_called_once_with()

    async def test_post_init_starts_client_and_always_on_refresher(
        self,
        service: SlotBotService,
        config: SlotBotServiceConfig,
        s21_client_mock: School21Client,
        booking_manager_mock: BookingManager,
        tg_app_mock: Application,
    ) -> None:
        config.bot.should_refresh_bookings_on_active_bots = False

        await service._post_init(tg_app_mock)

        s21_client_mock.start.assert_awaited_once_with()
        booking_manager_mock.start_refreshing.assert_awaited_once()
        assert booking_manager_mock.start_refreshing.await_args.kwargs["run_immediately"] is False

    async def test_post_init_does_not_start_on_active_bots_refresher(
        self,
        service: SlotBotService,
        config: SlotBotServiceConfig,
        s21_client_mock: School21Client,
        booking_manager_mock: BookingManager,
        tg_app_mock: Application,
    ) -> None:
        config.bot.should_refresh_bookings_on_active_bots = True

        await service._post_init(tg_app_mock)

        s21_client_mock.start.assert_awaited_once_with()
        booking_manager_mock.start_refreshing.assert_not_awaited()

    async def test_post_stop_deletes_menu_messages_and_stops_client(
        self,
        service: SlotBotService,
        config: SlotBotServiceConfig,
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        tg_app_mock: Application,
    ) -> None:
        chat_id = config.bot.tg_chat_id.get_secret_value()
        tg_app_mock.chat_data = {
            chat_id: ChatData(
                menu_msg_id=100,
                menu_error_msg_id=101,
            )
        }

        await service._post_stop(tg_app_mock)

        deleted_ids = [call.args[0] for call in messenger_mock.safe_delete.await_args_list]
        assert deleted_ids == [101, 100]
        s21_client_mock.stop.assert_awaited_once_with()

    async def test_post_stop_without_chat_data_still_stops_client(
        self,
        service: SlotBotService,
        config: SlotBotServiceConfig,
        s21_client_mock: School21Client,
        messenger_mock: Messenger,
        tg_app_mock: Application,
    ) -> None:
        tg_app_mock.chat_data = {}

        await service._post_stop(tg_app_mock)

        messenger_mock.safe_delete.assert_not_awaited()
        s21_client_mock.stop.assert_awaited_once_with()
