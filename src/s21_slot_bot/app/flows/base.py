import enum
from abc import ABC, abstractmethod
from enum import StrEnum

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity, Update
from telegram._utils.types import MarkdownVersion
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.consts import MAX_REQUIRED_REVIEWS, MIN_REQUIRED_REVIEWS, PYDANTIC_DATETIME_DOCS_URL
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import CustomContext, FlowCategory, Mode, Screen
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.logger import get_user_input_logger
from s21_slot_bot.common.markdown import MarkdownV2Escaper


class FlowAction(StrEnum): ...


class InputFlowAction(FlowAction):
    PICK_MODE = enum.auto()
    PICK_NUM_REVIEWS = enum.auto()
    PICK_FROM = enum.auto()
    PICK_TO = enum.auto()

    BACK = enum.auto()


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


class CustomInputFlow(Flow, ABC):
    @property
    @abstractmethod
    def _action_to_screen(self) -> dict[FlowAction, Screen]:
        raise NotImplementedError

    async def pick_mode(
        self,
        user_input: Update | CallbackQuery,
        context: CustomContext,
    ) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Picking mode in category `%s`...", self._category)
        action = InputFlowAction.PICK_MODE
        prev_action = self._get_prev_action(action, context)
        # action = StartFlowAction.PICK_MODE
        # self._screen_set(context, Screen.START_PICK_MODE)
        buttons = [
            [
                InlineKeyboardButton(
                    "🔎 Искать слоты",
                    callback_data=f"{self._category}:{action}:{Mode.ONLY_FIND}",
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Записаться",
                    callback_data=f"{self._category}:{action}:{Mode.FIND_AND_BOOK}",
                )
            ],
        ]
        if prev_action and len(context.chat_data.projects_map) > 1:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{self._category}:{InputFlowAction.BACK}:{prev_action}",
                    )
                ]
            )
        kb = InlineKeyboardMarkup(buttons)
        text = self._get_chosen_project_info_text(context, action, is_markdown=True) + "выбери режим:"
        await self._messenger.render_menu_message(context, text, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    async def pick_num_reviews(
        self,
        query: CallbackQuery,
        context: CustomContext,
    ) -> None:
        logger = get_user_input_logger(query)
        logger.info("Picking number of reviews in category `%s`...", self._category)
        action = InputFlowAction.PICK_NUM_REVIEWS
        prev_action = self._get_prev_action(action, context)
        # action = StartFlowAction.PICK_NUM_REVIEWS
        # self._screen_set(context, Screen.START_PICK_NUM)
        buttons = [
            [
                InlineKeyboardButton(str(num), callback_data=f"{self._category}:{action}:{num}")
                for num in range(MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS + 1)
            ],
        ]
        if prev_action:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{self._category}:{InputFlowAction.BACK}:{prev_action}",
                    )
                ],
            )
        kb = InlineKeyboardMarkup(buttons)
        text = self._get_chosen_project_info_text(context, action, is_markdown=True) + "выбери количество проверок:"
        await self._messenger.render_menu_message(context, text, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    async def pick_from(
        self,
        user_input: Update | CallbackQuery,
        context: CustomContext,
    ) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Picking search start time in category `%s`...", self._category)
        action = InputFlowAction.PICK_FROM
        prev_action = self._get_prev_action(action, context)
        # action = StartFlowAction.PICK_FROM
        # context.chat_data.screen = Screen.START_PICK_FROM
        self._set_screen(action, context)
        # prev_action = (
        #     StartFlowAction.PICK_NUM_REVIEWS
        #     if context.chat_data.start_mode == Mode.FIND_AND_BOOK
        #     else StartFlowAction.PICK_MODE
        # )
        buttons = [
            [
                InlineKeyboardButton("сейчас", callback_data=f"{self._category}:{action}:PT0S"),
                InlineKeyboardButton("+30м", callback_data=f"{self._category}:{action}:PT30M"),
                InlineKeyboardButton("+1ч", callback_data=f"{self._category}:{action}:PT1H"),
            ],
        ]
        if prev_action:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{self._category}:{InputFlowAction.BACK}:{prev_action}",
                    )
                ],
            )
        kb = InlineKeyboardMarkup(buttons)
        text = (
            self._get_chosen_project_info_text(context, action, is_markdown=True) + "выбери начальное время поиска\n"
            "(или введи вручную в формате [YYYY-MM-DD] HH:MM[:SS] - "
            f"[поддерживаемые строковые форматы]({PYDANTIC_DATETIME_DOCS_URL})):"
        )
        await self._messenger.render_menu_message(context, text, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    # @abstractmethod
    # async def custom_from(self, update: Update, context: CustomContext) -> None:
    #     raise NotImplementedError

    # logger = get_user_input_logger(update)
    # logger.info("Parsing custom search start time...")
    # try:
    #     now = datetime.now(tz=context.bot.defaults.tzinfo)
    #     start_from = str_to_dt_with_from(update.message.text, context.bot.defaults.tzinfo, now, logger)
    #     context.chat_data.start_from = start_from
    # except InvalidUserInputError as e:
    #     await self.pick_from(update, context)
    #     raise e
    #
    # await self.pick_to(update, context)

    async def pick_to(
        self,
        user_input: Update | CallbackQuery,
        context: CustomContext,
    ) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Picking search end time in category `%s`...", self._category)
        action = InputFlowAction.PICK_TO
        prev_action = self._get_prev_action(action, context)
        # action = StartFlowAction.PICK_TO
        # context.chat_data.screen = Screen.START_PICK_TO
        self._set_screen(action, context)
        buttons = [
            [
                InlineKeyboardButton(f"+{hour}ч", callback_data=f"{self._category}:{action}:PT{hour}H")
                for hour in [1, 2, 4, 8, 12]
            ],
        ]
        if prev_action:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{self._category}:{InputFlowAction.BACK}:{prev_action}",
                    )
                ],
            )
        kb = InlineKeyboardMarkup(buttons)
        text = (
            self._get_chosen_project_info_text(context, action, is_markdown=True)
            + "выбери конечное время поиска относительно начала\n"
            "(или введи вручную в формате [YYYY-MM-DD] HH:MM[:SS] - "
            f"[поддерживаемые строковые форматы]({PYDANTIC_DATETIME_DOCS_URL})):"
        )
        await self._messenger.render_menu_message(context, text, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    # @abstractmethod
    # async def custom_to(self, update: Update, context: CustomContext) -> None:
    #     raise NotImplementedError

    # logger = get_user_input_logger(update)
    # logger.info("Parsing custom search end time...")
    # try:
    #     start_from = context.chat_data.start_from
    #     if not start_from:
    #         raise InternalError("начальное время поиска не задано", location=context.chat_data.model_dump())
    #     start_to = str_to_dt_with_from(update.message.text, context.bot.defaults.tzinfo, start_from, logger)
    #     if start_to <= start_from:
    #         raise InvalidUserInputError(f"конечное время должно быть позже начального ({dt_to_pretty(start_to)})")
    #     context.chat_data.start_to = start_to
    # except InvalidUserInputError as e:
    #     await self.pick_to(update, context)
    #     raise e
    #
    # await self.confirm(update, context)

    def _set_screen(self, action: FlowAction, context: CustomContext) -> None:
        screen = self._action_to_screen.get(action)
        if screen:
            context.chat_data.screen = screen

    @abstractmethod
    def _get_prev_action(self, action: FlowAction, context: CustomContext) -> FlowAction | None:
        raise NotImplementedError

    @abstractmethod
    def _get_chosen_project_info_text(
        self, context: CustomContext, action: FlowAction | None = None, is_markdown: bool = False
    ) -> str:
        raise NotImplementedError
