from unittest.mock import AsyncMock, MagicMock

import pytest
import telegram
from telegram import Message
from telegram.constants import ParseMode

from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import CustomContext
from s21_slot_bot.common.logger import LoggerLike


class TestMessenger:
    async def test_send_marks_menu_for_moving(
        self,
        messenger: Messenger,
        context: CustomContext,
    ) -> None:
        message = MagicMock(spec=Message)
        messenger._bot.send_message = AsyncMock(return_value=message)

        actual = await messenger.send(context, "hello")

        assert actual is message
        assert context.bot_data.chat_should_move_menu[messenger._chat_id] is True

    async def test_send_escapes_markdown(
        self,
        messenger: Messenger,
        context: CustomContext,
    ) -> None:
        messenger._bot.send_message = AsyncMock(return_value=MagicMock(spec=Message))

        await messenger.send(
            context,
            "hello.world",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

        assert messenger._bot.send_message.await_args.args[1] == r"hello\.world"

    async def test_safe_delete_ignores_bad_request(
        self,
        messenger: Messenger,
        logger_mock: LoggerLike,
    ) -> None:
        messenger._bot.delete_message = AsyncMock(side_effect=telegram.error.BadRequest("message to delete not found"))

        await messenger.safe_delete(123, logger_mock)

    async def test_render_menu_message_reuses_existing_message(
        self,
        messenger: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        context.ensured_chat_data.menu_msg_id = 123
        messenger._bot.edit_message_text = AsyncMock()

        await messenger.render_menu_message(context, "status", logger_mock)

        assert context.ensured_chat_data.menu_msg_id == 123
        messenger._bot.edit_message_text.assert_awaited_once()

    async def test_render_menu_message_moves_menu_after_regular_message(
        self,
        messenger: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        context.bot_data.chat_should_move_menu[messenger._chat_id] = True
        context.ensured_chat_data.menu_msg_id = 123
        messenger.safe_delete = AsyncMock()
        messenger._ensure_message = AsyncMock(return_value=456)
        messenger._bot.edit_message_text = AsyncMock()

        await messenger.render_menu_message(context, "status", logger_mock)

        messenger.safe_delete.assert_awaited_once_with(123, logger_mock)
        assert context.bot_data.chat_should_move_menu[messenger._chat_id] is False
        assert context.ensured_chat_data.menu_msg_id == 456

    async def test_render_menu_error_ignores_not_modified(
        self,
        messenger: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        context.ensured_chat_data.menu_error_msg_id = 123
        messenger._bot.edit_message_text = AsyncMock(side_effect=telegram.error.BadRequest("Message is not modified"))

        await messenger.render_menu_error(context, "same", logger_mock)

    async def test_render_menu_error_reraises_other_bad_request(
        self,
        messenger: Messenger,
        context: CustomContext,
        logger_mock: LoggerLike,
    ) -> None:
        context.ensured_chat_data.menu_error_msg_id = 123
        messenger._bot.edit_message_text = AsyncMock(side_effect=telegram.error.BadRequest("other error"))

        with pytest.raises(telegram.error.BadRequest) as exc_info:
            await messenger.render_menu_error(context, "bad", logger_mock)

        assert exc_info.value.message == "other error"
