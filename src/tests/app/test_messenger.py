from unittest.mock import AsyncMock, MagicMock

import pytest
import telegram
from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ExtBot

from s21_slot_bot.app.errors import InternalError
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import CustomContext
from s21_slot_bot.common.logger import LoggerLike


class TestMessenger:
    async def test_start_menu(
        self,
        messenger: Messenger,
        update_mock: Update,
        message: Message,
        logger_mock: LoggerLike,
    ) -> None:
        update_mock.message.reply_text = AsyncMock()
        messenger.safe_delete = AsyncMock()
        await messenger.start_menu(update_mock, logger_mock)
        assert messenger.safe_delete.await_args_list[0].args[0] == message.message_id

    async def test_start_menu_requires_message(
        self,
        messenger: Messenger,
        update_mock: Update,
        logger_mock: LoggerLike,
    ) -> None:
        update_mock.message = None
        with pytest.raises(InternalError):
            await messenger.start_menu(update_mock, logger_mock)

    async def test_send_and_markdown(
        self,
        messenger: Messenger,
        bot_mock: ExtBot,
        context: CustomContext,
    ) -> None:
        bot_mock.send_message = AsyncMock(return_value=MagicMock(spec=Message))
        await messenger.send(context, "hello.world", parse_mode=ParseMode.MARKDOWN_V2)
        assert bot_mock.send_message.await_args.args[1] == r"hello\.world"
        assert context.bot_data.chat_should_move_menu[messenger._chat_id] is True

    async def test_safe_delete(
        self,
        messenger: Messenger,
        bot_mock: ExtBot,
        logger_mock: LoggerLike,
    ) -> None:
        bot_mock.delete_message = AsyncMock()
        await messenger.safe_delete(None, logger_mock)
        bot_mock.delete_message.assert_not_awaited()
        await messenger.safe_delete(10, logger_mock)
        bot_mock.delete_message.assert_awaited_once()

        bot_mock.delete_message = AsyncMock(side_effect=telegram.error.BadRequest("gone"))
        await messenger.safe_delete(10, logger_mock)

    async def test_render_menu_message(
        self,
        messenger: Messenger,
        bot_mock: ExtBot,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        message = MagicMock(spec=Message)
        message.message_id = 20
        bot_mock.send_message = AsyncMock(return_value=message)
        bot_mock.edit_message_text = AsyncMock()
        await messenger.render_menu_message(context, "hello.world", logger_mock, parse_mode=ParseMode.MARKDOWN_V2)
        assert context.ensured_chat_data.menu_msg_id == 20
        assert bot_mock.edit_message_text.await_args.kwargs["text"] == r"hello\.world"

    async def test_render_menu_message_moves_menu(
        self,
        messenger: Messenger,
        bot_mock: ExtBot,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        context.ensured_chat_data.menu_msg_id = 10
        context.bot_data.chat_should_move_menu[messenger._chat_id] = True
        messenger.safe_delete = AsyncMock()
        messenger._ensure_message = AsyncMock(return_value=20)
        bot_mock.edit_message_text = AsyncMock()
        await messenger.render_menu_message(context, "status", logger_mock)
        assert context.ensured_chat_data.menu_msg_id == 20
        assert context.bot_data.chat_should_move_menu[messenger._chat_id] is False

    async def test_render_menu_error(
        self,
        messenger: Messenger,
        bot_mock: ExtBot,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        messenger._ensure_message = AsyncMock(return_value=10)
        bot_mock.edit_message_text = AsyncMock()
        await messenger.render_menu_error(context, "hello.world", logger_mock, parse_mode=ParseMode.MARKDOWN_V2)
        assert bot_mock.edit_message_text.await_args.kwargs["text"] == r"hello\.world"

        bot_mock.edit_message_text = AsyncMock(side_effect=telegram.error.BadRequest("Message is not modified"))
        await messenger.render_menu_error(context, "same", logger_mock)

        bot_mock.edit_message_text = AsyncMock(side_effect=telegram.error.BadRequest("other error"))
        with pytest.raises(telegram.error.BadRequest):
            await messenger.render_menu_error(context, "bad", logger_mock)

    async def test_ensure_message(
        self,
        messenger: Messenger,
        bot_mock: ExtBot,
    ) -> None:
        assert await messenger._ensure_message(10) == 10
        message = MagicMock(spec=Message)
        message.message_id = 20
        bot_mock.send_message = AsyncMock(return_value=message)
        assert await messenger._ensure_message(None) == 20
