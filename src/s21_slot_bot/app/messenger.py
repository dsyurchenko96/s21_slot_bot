import telegram.error
from telegram import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ExtBot

from s21_slot_bot.app.models import CustomContext, MenuButton
from s21_slot_bot.common.logger import LoggerLike
from s21_slot_bot.common.markdown import MarkdownV2Escaper

MAIN_MENU_KB = ReplyKeyboardMarkup(
    [
        [MenuButton.START, MenuButton.STOP, MenuButton.DELETE],
        [MenuButton.EDIT, MenuButton.STATUS],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


class Messenger:
    def __init__(self, chat_id: int, bot: ExtBot):
        self._chat_id = chat_id
        self._bot = bot
        self._markdown_escaper = MarkdownV2Escaper()

    async def send(
        self,
        context: CustomContext,
        text: str,
        kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
        parse_mode: ParseMode | None = None,
    ) -> Message:
        if parse_mode == ParseMode.MARKDOWN_V2:
            text = self._markdown_escaper.escape(text)
        message = await self._bot.send_message(
            self._chat_id,
            text,
            parse_mode=parse_mode,
            # reply_markup=MAIN_MENU_KB,
        )
        context.bot_data.chat_should_move_menu[self._chat_id] = True
        return message

    async def safe_delete(self, message_id: int | None, logger: LoggerLike) -> None:
        if not message_id:
            return

        try:
            await self._bot.delete_message(self._chat_id, message_id)
        except telegram.error.BadRequest as e:
            logger.info("Not deleted message `%s`: `%s`", message_id, e)

    async def render_menu_message(
        self,
        context: CustomContext,
        text: str,
        logger: LoggerLike,
        kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
        parse_mode: ParseMode | None = None,
    ) -> None:
        if context.bot_data.chat_should_move_menu.get(self._chat_id):
            await self.safe_delete(context.chat_data.menu_msg_id, logger)
            context.bot_data.chat_should_move_menu[self._chat_id] = False
            context.chat_data.menu_msg_id = None

        context.chat_data.menu_msg_id = await self._ensure_message(context.chat_data.menu_msg_id)
        if parse_mode == ParseMode.MARKDOWN_V2:
            text = self._markdown_escaper.escape(text)
        await self._bot.edit_message_text(
            chat_id=self._chat_id,
            message_id=context.chat_data.menu_msg_id,
            text=text,
            reply_markup=kb,
            parse_mode=parse_mode,
        )

    async def render_menu_error(
        self,
        context: CustomContext,
        text: str,
        logger: LoggerLike,
        kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
        parse_mode: ParseMode | None = None,
    ) -> None:
        context.chat_data.menu_error_msg_id = await self._ensure_message(context.chat_data.menu_error_msg_id)

        if parse_mode == ParseMode.MARKDOWN_V2:
            text = self._markdown_escaper.escape(text)
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=context.chat_data.menu_error_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode=parse_mode,
            )
        except telegram.error.BadRequest as error:
            if "not modified" in error.message.lower():
                logger.info("No update has taken place in menu error: %s", error)
                return
            raise

    async def _ensure_message(self, message_id: int | None) -> int:
        if message_id:
            return message_id

        message = await self._bot.send_message(
            self._chat_id,
            "...",
            # reply_markup=MAIN_MENU_KB,
        )
        return message.message_id
