import enum
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Coroutine

from pydantic import TypeAdapter
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.consts import MAX_REQUIRED_REVIEWS, MIN_REQUIRED_REVIEWS
from s21_slot_bot.app.flows.base import Flow, FlowAction
from s21_slot_bot.app.messenger import Messenger
from s21_slot_bot.app.models import BotConfig, BotInstance, CustomContext, FlowCategory, Mode, RequiredReviews, Screen
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.exceptions import (
    InternalError,
    InvalidCallbackDataError,
    InvalidUserInputError,
    MenuError,
    School21Error,
)
from s21_slot_bot.common.logger import get_user_input_logger
from s21_slot_bot.common.random import random_id
from s21_slot_bot.common.strings import ensure_str
from s21_slot_bot.common.time import dt_to_pretty, str_to_dt_with_from


# NOTE: ordered
class StartFlowAction(FlowAction):
    LIST_PROJECTS = enum.auto()
    PICK_PROJECT = enum.auto()
    PICK_MODE = enum.auto()
    PICK_NUM_REVIEWS = enum.auto()
    PICK_FROM = enum.auto()
    PICK_TO = enum.auto()
    CONFIRM = enum.auto()
    FINALIZE = enum.auto()

    BACK = enum.auto()

    def get_index(self) -> int:
        return list(StartFlowAction).index(self)


class StartFlow(Flow):
    def __init__(self, s21_client: School21Client, bot_manager: BotManager, messenger: Messenger):
        super().__init__(s21_client, bot_manager, messenger)
        self._action_to_method: dict[
            StartFlowAction, Callable[[Update | CallbackQuery, CustomContext], Coroutine[Any, Any, None]]
        ] = {
            StartFlowAction.LIST_PROJECTS: self.list_projects,
            StartFlowAction.PICK_MODE: self.pick_mode,
            StartFlowAction.PICK_NUM_REVIEWS: self.pick_num_reviews,
            StartFlowAction.PICK_FROM: self.pick_from,
            StartFlowAction.PICK_TO: self.pick_to,
            StartFlowAction.CONFIRM: self.confirm,
            StartFlowAction.FINALIZE: self.finalize,
        }

    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        action = callback_data.pop()
        match action:
            case StartFlowAction.LIST_PROJECTS:
                await self.list_projects(query, context)
            case StartFlowAction.PICK_PROJECT:
                proj_id = int(callback_data.pop())
                # TODO: store project map only and get id and name from it?
                context.chat_data.start_project_id = proj_id
                context.chat_data.start_project_name = context.chat_data.projects_map.get(proj_id, proj_id)
                await self.pick_mode(query, context)
            case StartFlowAction.PICK_MODE:
                mode = Mode(callback_data.pop())
                context.chat_data.start_mode = mode
                match mode:
                    case Mode.ONLY_FIND:
                        context.chat_data.start_required_reviews = MIN_REQUIRED_REVIEWS
                        await self.pick_from(query, context)
                    case Mode.FIND_AND_BOOK:
                        await self.pick_num_reviews(query, context)
            case StartFlowAction.PICK_NUM_REVIEWS:
                num_reviews = TypeAdapter(RequiredReviews).validate_strings(callback_data.pop())
                context.chat_data.start_required_reviews = num_reviews
                await self.pick_from(query, context)
            case StartFlowAction.PICK_FROM:
                now = datetime.now(tz=self._bot_manager.bot_config.timezone)
                from_choice = str_to_dt_with_from(
                    callback_data.pop(), self._bot_manager.bot_config.timezone, now, logger
                )
                context.chat_data.start_from = from_choice
                await self.pick_to(query, context)
            case StartFlowAction.PICK_TO:
                from_dt = context.chat_data.start_from
                if not from_dt:
                    raise InternalError("начальное время поиска не задано", location=context.chat_data.model_dump())
                to_choice = str_to_dt_with_from(
                    callback_data.pop(), self._bot_manager.bot_config.timezone, from_dt, logger
                )
                context.chat_data.start_to = to_choice
                await self.confirm(query, context)
            case StartFlowAction.CONFIRM:
                await self.finalize(query, context)
            case StartFlowAction.FINALIZE:
                return
            case StartFlowAction.BACK:
                prev_action = StartFlowAction(callback_data.pop())
                prev_method = self._action_to_method.get(prev_action)
                await prev_method(query, context)
            case _:
                raise InvalidCallbackDataError

    async def list_projects(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Listing projects...")
        # if self._bot_manager.running_count() >= self._bot_manager.bot_config.max_bots:
        #     text = f"Максимальное количество ботов превышено ({self._bot_manager.bot_config.max_bots}) - останови/удали имеющихся или поменяй количество"
        #     await self._messenger.render_menu(context, text)
        #     return
        self._bot_manager.check_bot_limits()

        # self._screen_set(context, Screen.START_PICK_PROJECT)
        try:
            user_id = self._s21_client.get_user_id(logger)
            projects = self._s21_client.get_reviewed_projects(user_id, logger)
        except School21Error as e:
            raise MenuError(f"не удалось получить проекты: {e}") from e
            # await render_menu(user_input, context, text)
            # return

        if not projects:
            # raise MenuError("нет активных проектов на проверке")
            await self._messenger.render_menu_message(context, "📭 нет активных проектов на проверке")
            return

        context.chat_data.projects_map = {project.id: project.name for project in projects}

        if len(projects) == 1:
            project = projects[0]
            context.chat_data.start_project_id = project.id
            context.chat_data.start_project_name = project.name
            await self.pick_mode(user_input, context)
            return

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{project.name} ({project.id})",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_PROJECT}:{project.id}",
                    )
                ]
                for project in projects[:20]
            ]
        )
        await self._messenger.render_menu_message(context, "выбери проект:", kb=kb)

    async def pick_mode(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Picking mode...")
        action = StartFlowAction.PICK_MODE
        # self._screen_set(context, Screen.START_PICK_MODE)
        buttons = [
            [
                InlineKeyboardButton(
                    "🔎 Искать слоты",
                    callback_data=f"{FlowCategory.START}:{action}:{Mode.ONLY_FIND}",
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Записаться",
                    callback_data=f"{FlowCategory.START}:{action}:{Mode.FIND_AND_BOOK}",
                )
            ],
        ]
        projects = context.chat_data.projects_map
        if len(projects) > 1:
            buttons.append(
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.BACK}:{StartFlowAction.LIST_PROJECTS}",
                    )
                ]
            )
        kb = InlineKeyboardMarkup(buttons)
        text = self._get_chosen_project_info_text(action, context) + "выбери режим:"
        await self._messenger.render_menu_message(context, text, kb=kb)

    async def pick_num_reviews(self, query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        logger.info("Picking number of reviews...")
        action = StartFlowAction.PICK_NUM_REVIEWS
        # self._screen_set(context, Screen.START_PICK_NUM)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(str(num), callback_data=f"{FlowCategory.START}:{action}:{num}")
                    for num in range(MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS + 1)
                ],
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.BACK}:{StartFlowAction.PICK_MODE}",
                    )
                ],
            ]
        )
        text = self._get_chosen_project_info_text(action, context) + "выбери количество проверок:"
        await self._messenger.render_menu_message(context, text, kb=kb)

    async def pick_from(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Picking search start time...")
        action = StartFlowAction.PICK_FROM
        context.chat_data.screen = Screen.START_PICK_FROM
        prev_action = (
            StartFlowAction.PICK_NUM_REVIEWS
            if context.chat_data.start_mode == Mode.FIND_AND_BOOK
            else StartFlowAction.PICK_MODE
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("сейчас", callback_data=f"{FlowCategory.START}:{action}:PT0S"),
                    InlineKeyboardButton("+30м", callback_data=f"{FlowCategory.START}:{action}:PT30M"),
                    InlineKeyboardButton("+1ч", callback_data=f"{FlowCategory.START}:{action}:PT1H"),
                ],
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.BACK}:{prev_action}",
                    )
                ],
            ]
        )
        text = (
            self._get_chosen_project_info_text(action, context)
            + "выбери начальное время поиска\n(или введи вручную в формате [YYYY-MM-DD] HH:MM[:SS]):"
        )
        await self._messenger.render_menu_message(context, text, kb=kb)

    async def custom_from(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Parsing custom search start time...")
        try:
            now = datetime.now(tz=self._bot_manager.bot_config.timezone)
            start_from = str_to_dt_with_from(update.message.text, self._bot_manager.bot_config.timezone, now, logger)
            context.chat_data.start_from = start_from
        except InvalidUserInputError as e:
            await self.pick_from(update, context)
            raise e

        await self.pick_to(update, context)

    async def pick_to(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Picking search end time...")
        action = StartFlowAction.PICK_TO
        context.chat_data.screen = Screen.START_PICK_TO
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(f"+{hour}ч", callback_data=f"{FlowCategory.START}:{action}:PT{hour}H")
                    for hour in [1, 2, 4, 8, 12]
                ],
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.BACK}:{StartFlowAction.PICK_FROM}",
                    )
                ],
            ]
        )
        text = (
            self._get_chosen_project_info_text(action, context)
            + "выбери конечное время поиска относительно начала\n(или введи вручную в формате [YYYY-MM-DD] HH:MM[:SS]):"
        )
        await self._messenger.render_menu_message(context, text, kb=kb)

    async def custom_to(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Parsing custom search end time...")
        try:
            start_from = context.chat_data.start_from
            if not start_from:
                raise InternalError("начальное время поиска не задано", location=context.chat_data.model_dump())
            start_to = str_to_dt_with_from(
                update.message.text, self._bot_manager.bot_config.timezone, start_from, logger
            )
            if start_to <= start_from:
                raise InvalidUserInputError(f"конечное время должно быть позже начального ({dt_to_pretty(start_to)})")
            context.chat_data.start_to = start_to
        except InvalidUserInputError as e:
            await self.pick_to(update, context)
            raise e

        await self.confirm(update, context)

    async def confirm(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Confirming the chosen bot search parameters...")
        action = StartFlowAction.CONFIRM
        # self._screen_set(context, Screen.START_CONFIRM)

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🚀 старт", callback_data=f"{FlowCategory.START}:{action}")],
                [
                    InlineKeyboardButton(
                        "⏪ Назад",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.BACK}:{StartFlowAction.PICK_TO}",
                    )
                ],
            ]
        )
        text = (
            self._get_chosen_project_info_text(action, context)
            + f"активных ботов: {len(self._bot_manager.running())} / максимум {self._bot_manager.bot_config.max_bots}"
        )
        await self._messenger.render_menu_message(context, text, kb=kb)

    async def finalize(self, query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        logger.info("Finalizing the chosen bot search parameters...")
        action = StartFlowAction.CONFIRM
        text = self._get_chosen_project_info_text(action, context)
        self._bot_manager.check_bot_limits()

        bot_id = random_id()
        cfg = BotConfig(
            bot_id=bot_id,
            project_id=context.chat_data.start_project_id,
            project_name=context.chat_data.start_project_name,
            required_reviews=context.chat_data.start_required_reviews,
            from_dt=context.chat_data.start_from,
            to_dt=context.chat_data.start_to,
            interval_sec=self._bot_manager.bot_config.poll_interval_sec,
            mode=context.chat_data.start_mode,
        )

        inst = BotInstance(cfg=cfg)
        text += f"✅ Запускаю бота #{bot_id}"
        await self._messenger.render_menu_message(context, text)
        self._bot_manager.start_bot(inst, context)
        logger.info("Started bot #%s", bot_id)

    def _get_chosen_project_info_text(self, action: StartFlowAction, context: CustomContext) -> str:
        lines = [
            f"проект: {ensure_str(context.chat_data.start_project_name)} (ID {ensure_str(context.chat_data.start_project_id)})",
            f"режим: {ensure_str(context.chat_data.start_mode, getter=lambda mode: mode.to_text())}",
            f"количество проверок: {ensure_str(context.chat_data.start_required_reviews)}",
            f"начало поиска: {ensure_str(context.chat_data.start_from, getter=dt_to_pretty)}",
            f"конец поиска: {ensure_str(context.chat_data.start_to, getter=dt_to_pretty)}",
        ]
        line_idx = action.get_index() - StartFlowAction.PICK_PROJECT.get_index()
        project_info_text = "\n".join(lines[:line_idx]) + "\n\n"
        return project_info_text
