from abc import ABC, abstractmethod

from telegram import CallbackQuery, InlineKeyboardMarkup, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.models import CustomContext, Screen
from s21_slot_bot.client.s21_client import School21Client


class Flow(ABC):
    def __init__(self, s21_client: School21Client, bot_manager: BotManager):
        self._s21_client = s21_client
        self._bot_manager = bot_manager

    @abstractmethod
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        raise NotImplementedError

    def _screen_set(self, ctx: CustomContext, scr: Screen) -> None:
        ctx.chat_data.screen = scr
