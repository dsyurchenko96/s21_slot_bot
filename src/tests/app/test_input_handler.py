from unittest.mock import AsyncMock, MagicMock

import pytest
import telegram
from telegram import CallbackQuery, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.errors import (
    ForbiddenError,
    InternalError,
    InvalidCallbackDataError,
    MenuError,
)
from s21_slot_bot.app.flows.collector import FlowCollector
from s21_slot_bot.app.input_handler import InputHandler
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import CustomContext, FlowCategory, Lifecycle, MenuButton, Screen
from s21_slot_bot.common.error import Error


class TestInputHandler:
    async def test_on_cmd_start_opens_menu(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        await input_handler.on_cmd_start(update_mock, context)

        messenger_mock.start_menu.assert_awaited_once()

    async def test_on_cmd_start_rejects_another_user(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        update_mock.effective_user.id += 1

        with pytest.raises(ForbiddenError):
            await input_handler.on_cmd_start(update_mock, context)

        messenger_mock.start_menu.assert_not_awaited()

    async def test_on_text_routes_menu_button(
        self,
        input_handler: InputHandler,
        flow_collector_mock: FlowCollector,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        update_mock.message.text = MenuButton.STATUS

        await input_handler.on_text(update_mock, context)

        flow_collector_mock.status.status_refresh.assert_awaited_once_with(update_mock, context)

    async def test_on_text_routes_custom_input_by_screen(
        self,
        input_handler: InputHandler,
        flow_collector_mock: FlowCollector,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        update_mock.message.text = "2026-08-17 12:00"
        context.ensured_chat_data.screen = Screen.START_PICK_FROM

        await input_handler.on_text(update_mock, context)

        flow_collector_mock.start.custom_from.assert_awaited_once_with(update_mock, context)

    async def test_on_text_renders_processing_message_when_menu_is_missing(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        flow_collector_mock: FlowCollector,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        update_mock.message.text = MenuButton.STATUS
        context.ensured_chat_data.menu_msg_id = None

        await input_handler.on_text(update_mock, context)

        assert messenger_mock.render_menu_message.await_args.args[1] == "обработка запроса..."
        flow_collector_mock.status.status_refresh.assert_awaited_once()

    async def test_on_text_rejects_unknown_input(
        self,
        input_handler: InputHandler,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        update_mock.message.text = "something else"
        context.ensured_chat_data.screen = Screen.MENU

        with pytest.raises(MenuError, match="выбери действие"):
            await input_handler.on_text(update_mock, context)

    async def test_on_callback_routes_to_selected_flow(
        self,
        input_handler: InputHandler,
        flow_collector_mock: FlowCollector,
        update_mock: Update,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        flow = MagicMock()
        flow.parse_callback = AsyncMock()
        flow_collector_mock.get_flow.return_value = flow
        query_mock.data = f"{FlowCategory.STATUS}:refresh"
        update_mock.message = None
        update_mock.callback_query = query_mock

        await input_handler.on_callback(update_mock, context)

        query_mock.answer.assert_awaited_once()
        flow_collector_mock.get_flow.assert_called_once_with(FlowCategory.STATUS)
        flow.parse_callback.assert_awaited_once_with(["refresh"], query_mock, context)

    async def test_on_callback_wraps_invalid_callback_data(
        self,
        input_handler: InputHandler,
        update_mock: Update,
        query_mock: CallbackQuery,
        context: CustomContext,
    ) -> None:
        query_mock.data = "not-a-category:value"
        update_mock.message = None
        update_mock.callback_query = query_mock

        with pytest.raises(InvalidCallbackDataError) as exc_info:
            await input_handler.on_callback(update_mock, context)

        assert exc_info.value.location == {"data": "not-a-category:value"}

    async def test_on_callback_requires_callback_query(
        self,
        input_handler: InputHandler,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        update_mock.callback_query = None

        with pytest.raises(InternalError):
            await input_handler.on_callback(update_mock, context)

    async def test_on_success_clears_menu_error(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        context.ensured_chat_data.menu_error_msg_id = 123

        await input_handler.on_success(update_mock, context)

        assert context.ensured_chat_data.menu_error_msg_id is None
        messenger_mock.safe_delete.assert_awaited_once()

    async def test_on_error_renders_menu_error(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        context.error = MenuError("bad input")

        await input_handler.on_error(update_mock, context)

        messenger_mock.render_menu_error.assert_awaited_once()
        messenger_mock.send.assert_not_awaited()

    async def test_on_error_sends_application_error(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        context.error = Error("backend failed")

        await input_handler.on_error(update_mock, context)

        messenger_mock.send.assert_awaited_once()
        messenger_mock.render_menu_error.assert_not_awaited()

    async def test_on_error_ignores_not_modified_telegram_error(
        self,
        input_handler: InputHandler,
        messenger_mock: Messenger,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        context.error = telegram.error.BadRequest("Message is not modified")

        await input_handler.on_error(update_mock, context)

        messenger_mock.send.assert_not_awaited()
        messenger_mock.render_menu_error.assert_not_awaited()

    async def test_on_error_marks_job_bot_failed(
        self,
        input_handler: InputHandler,
        bot_manager_mock: BotManager,
        update_mock: Update,
        context: CustomContext,
    ) -> None:
        context.error = RuntimeError("boom")
        context.job = MagicMock()
        context.job.name = "bot-1"

        await input_handler.on_error(update_mock, context)

        assert bot_manager_mock.stop_bot.call_args.args[0] == "bot-1"
        assert bot_manager_mock.stop_bot.call_args.kwargs["state"] == Lifecycle.FAILED
