import telegram.error
from telegram import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from telegram.ext import Application, ExtBot

from s21_slot_bot.app.models import CustomContext, MenuButton
from s21_slot_bot.common.logger import LoggerLike

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        [MenuButton.START, MenuButton.STOP],
        [MenuButton.EDIT, MenuButton.STATUS],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


class Messenger:
    def __init__(self, chat_id: int, bot: ExtBot):
        self._chat_id = chat_id
        self._bot = bot

    async def send(
        self,
        context: CustomContext,
        text: str,
        kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
    ) -> Message:
        message = await self._bot.send_message(
            self._chat_id,
            text,
            # reply_markup=MAIN_MENU_KB,
        )
        # TODO: figure out None chat_data in case of task exception
        context.chat_data.should_move_menu = True
        return message

    async def safe_delete(self, message_id: int | None, logger: LoggerLike) -> None:
        if not message_id:
            return

        try:
            await self._bot.delete_message(self._chat_id, message_id)
        except telegram.error.BadRequest as e:
            logger.info("Not deleted message `%s`: `%s`", message_id, e)

    async def delete(self, message_id: int) -> None:
        await self._bot.delete_message(self._chat_id, message_id)

    async def render_menu_message(
        self,
        context: CustomContext,
        text: str,
        kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
    ) -> None:
        if context.chat_data.should_move_menu and context.chat_data.menu_msg_id:
            await self.delete(context.chat_data.menu_msg_id)
            context.chat_data.should_move_menu = False
            context.chat_data.menu_msg_id = None

        context.chat_data.menu_msg_id = await self._ensure_message(context.chat_data.menu_msg_id)

        await self._bot.edit_message_text(
            chat_id=self._chat_id,
            message_id=context.chat_data.menu_msg_id,
            text=text,
            reply_markup=kb,
        )

    async def render_menu_error(
        self,
        context: CustomContext,
        text: str,
        kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
    ) -> None:
        context.chat_data.menu_error_msg_id = await self._ensure_message(context.chat_data.menu_error_msg_id)

        await self._bot.edit_message_text(
            chat_id=self._chat_id,
            message_id=context.chat_data.menu_error_msg_id,
            text=text,
            reply_markup=kb,
        )

    async def _ensure_message(self, message_id: int | None) -> int:
        if message_id:
            return message_id

        message = await self._bot.send_message(
            self._chat_id,
            "...",
            # reply_markup=MAIN_MENU_KB,
        )
        return message.message_id
