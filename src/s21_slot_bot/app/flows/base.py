from abc import ABC, abstractmethod

from telegram import InlineKeyboardMarkup, Update, CallbackQuery
from telegram.ext import ContextTypes

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.models import Screen
from s21_slot_bot.client.s21_client import School21Client


class Flow(ABC):
    def __init__(self, s21_client: School21Client, bot_manager: BotManager):
        self._s21_client = s21_client
        self._bot_manager = bot_manager

    @abstractmethod
    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        raise NotImplementedError

    def _screen_set(self, ctx: ContextTypes.DEFAULT_TYPE, scr: Screen) -> None:
        ctx.chat_data["screen"] = scr

    def _screen_get(self, ctx: ContextTypes.DEFAULT_TYPE) -> Screen:
        v = ctx.chat_data.get("screen", Screen.MENU)
        try:
            return Screen(v)
        except Exception:
            return Screen.MENU

    async def _respond_to_input(
        self, user_input: Update | CallbackQuery, message: str, kb: InlineKeyboardMarkup
    ) -> None:
        match user_input:
            case Update():
                await user_input.message.reply_text(message, reply_markup=kb)
            case CallbackQuery():
                await user_input.edit_message_text(message, reply_markup=kb)
