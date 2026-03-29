from telegram import CallbackQuery
from telegram.ext import ContextTypes

from s21_slot_bot.app.flows.base import Flow


class StopFlow(Flow):
    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        action = callback_data.pop()
        match action:

