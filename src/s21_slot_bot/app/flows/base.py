from abc import ABC, abstractmethod
from enum import StrEnum

from telegram import CallbackQuery, InlineKeyboardMarkup, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import CustomContext, FlowCategory, Screen
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import get_user_input_logger

ACTION_BACK = "back"


class FlowAction(StrEnum): ...


class Flow(ABC):
    def __init__(
        self, s21_client: School21Client, bot_manager: BotManager, messenger: Messenger, category: FlowCategory
    ):
        self._s21_client = s21_client
        self._bot_manager = bot_manager
        self._messenger = messenger
        self._category = category

    @abstractmethod
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        raise NotImplementedError

    # async def pick_from(
    #     self,
    #     user_input: Update | CallbackQuery,
    #     context: CustomContext,
    #     action: FlowAction,
    #     prev_action: FlowAction | None = None,
    # ) -> None:
    #     logger = get_user_input_logger(user_input)
    #     logger.info("Picking search start time...")
    #     action = StartFlowAction.PICK_FROM
    #     context.chat_data.screen = Screen.START_PICK_FROM
    #     prev_action = (
    #         StartFlowAction.PICK_NUM_REVIEWS
    #         if context.chat_data.start_mode == Mode.FIND_AND_BOOK
    #         else StartFlowAction.PICK_MODE
    #     )
    #     kb = InlineKeyboardMarkup(
    #         [
    #             [
    #                 InlineKeyboardButton("сейчас", callback_data=f"{self._category}:{action}:PT0S"),
    #                 InlineKeyboardButton("+30м", callback_data=f"{self._category}:{action}:PT30M"),
    #                 InlineKeyboardButton("+1ч", callback_data=f"{self._category}:{action}:PT1H"),
    #             ],
    #             [
    #                 InlineKeyboardButton(
    #                     "⏪ Назад",
    #                     callback_data=f"{self._category}:{StartFlowAction.BACK}:{prev_action}",
    #                 )
    #             ],
    #         ]
    #     )
    #     text = (
    #         self._get_chosen_project_info_text(action, context)
    #         + "выбери начальное время поиска\n(или введи вручную в формате [YYYY-MM-DD] HH:MM[:SS]):"
    #     )
    #     await self._messenger.render_menu_message(context, text, kb=kb)
