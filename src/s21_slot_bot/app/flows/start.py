import enum
import logging
import secrets
from datetime import datetime
from enum import StrEnum
from typing import Final, Callable, Coroutine, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, CallbackQuery
from telegram.ext import ContextTypes

from s21_slot_bot.app.bot_manager import BotManager
from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import Screen, BotConfig, BotInstance, FlowCategory, Mode
from s21_slot_bot.client.s21_client import School21Client
from s21_slot_bot.common.time import str_to_dt, dt_to_pretty, str_to_dt_with_from

# TODO: wrap
_logger = logging.getLogger(__name__)


class StartFlowAction(StrEnum):
    PICK_PROJECTS = enum.auto()
    PICK_NUM_REVIEWS = enum.auto()
    PICK_FROM = enum.auto()
    PICK_TO = enum.auto()
    PICK_MODE = enum.auto()
    CONFIRM = enum.auto()
    FINALIZE = enum.auto()


class StartFlow(Flow):
    ORDER: Final[tuple[StartFlowAction]] = tuple(StartFlowAction)

    def __init__(self, s21_client: School21Client, bot_manager: BotManager):
        super().__init__(s21_client, bot_manager)
        self.action_to_func: Final[
            dict[StartFlowAction, Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, None, None]]]
        ] = {
            StartFlowAction.PICK_PROJECTS: self.pick_projects,
            StartFlowAction.PICK_NUM_REVIEWS: self.pick_num_reviews,
            StartFlowAction.PICK_FROM: self.pick_from,
            StartFlowAction.PICK_TO: self.pick_to,
            StartFlowAction.PICK_MODE: self.pick_mode,
            StartFlowAction.CONFIRM: self.confirm,
            StartFlowAction.FINALIZE: self.finalize,
        }

    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        action = callback_data.pop()
        match action:
            case StartFlowAction.PICK_PROJECTS:
                proj_id = callback_data.pop()
                # TODO: store project map only and get id and name from it?
                context.chat_data["start_project_id"] = proj_id
                context.chat_data["start_project_name"] = context.chat_data.get("projects_map", {}).get(
                    proj_id, proj_id
                )
            case StartFlowAction.PICK_NUM_REVIEWS:
                num_reviews = int(callback_data.pop())
                context.chat_data["start_required_reviews"] = num_reviews
            case StartFlowAction.PICK_FROM:
                now = datetime.now(tz=self._bot_manager.bot_config.timezone)
                # TODO: add support for custom time input
                from_choice = str_to_dt_with_from(callback_data.pop(), self._bot_manager.bot_config.timezone, now)
                context.chat_data["start_from"] = from_choice
            case StartFlowAction.PICK_TO:
                from_dt: datetime = context.chat_data["start_from"]
                to_choice = str_to_dt_with_from(callback_data.pop(), self._bot_manager.bot_config.timezone, from_dt)
                context.chat_data["start_to"] = to_choice
            case StartFlowAction.PICK_MODE:
                mode = Mode(callback_data.pop())
                context.chat_data["start_dry_run"] = mode
            case StartFlowAction.CONFIRM:
                pass
            case StartFlowAction.FINALIZE:
                return
            case _:
                raise InvalidCallbackData

        next_action = self.ORDER[self.ORDER.index(action) + 1]
        next_func = self.action_to_func[next_action]
        await next_func(query, context)

    async def pick_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.message.chat_id
        if self._bot_manager.running_count(chat_id) >= self._bot_manager.bot_config.max_bots:
            await update.message.reply_text(
                f"Максимальное количество ботов превышено ({self._bot_manager.bot_config.max_bots}) - останови/удали имеющихся или поменяй количество ",
                reply_markup=MAIN_MENU_KB,
            )
            return

        self._screen_set(context, Screen.START_PICK_PROJECT)
        try:
            user_id = self._s21_client.get_user_id(_logger)
            projects = self._s21_client.get_reviewed_projects(user_id, _logger)
        except Exception as e:
            await update.message.reply_text(f"❌ не смог получить проекты: {e}", reply_markup=MAIN_MENU_KB)
            return

        if not projects:
            await update.message.reply_text("📭 нет активных проектов на проверке", reply_markup=MAIN_MENU_KB)
            return

        context.chat_data["projects_map"] = {project.id: project.name for project in projects}

        if len(projects) == 1:
            project = projects[0]
            context.chat_data["start_project_id"] = project.id
            context.chat_data["start_project_name"] = project.name
            await update.message.reply_text(
                f"проект выбран: {project.name} (id {project.id})", reply_markup=MAIN_MENU_KB
            )
            await self.pick_num_reviews(update, context)
            return

        kb = [
            [
                InlineKeyboardButton(
                    f"{project.name} ({project.id})",
                    callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_PROJECTS}:{project.id}",
                )
            ]
            for project in projects[:20]
        ]
        await update.message.reply_text("выбери проект:", reply_markup=InlineKeyboardMarkup(kb))

    async def pick_num_reviews(self, user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.START_PICK_NUM)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "1", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_NUM_REVIEWS}:1"
                    ),
                    InlineKeyboardButton(
                        "2", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_NUM_REVIEWS}:2"
                    ),
                    InlineKeyboardButton(
                        "3", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_NUM_REVIEWS}:3"
                    ),
                ],
            ]
        )
        message = "сколько проверок нужно (1–3)?"
        await self._respond_to_input(user_input, message, kb)

    async def pick_from(self, user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.START_PICK_FROM)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "сейчас", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_FROM}:PT0S"
                    ),
                    InlineKeyboardButton(
                        "+30м", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_FROM}:PT30M"
                    ),
                    InlineKeyboardButton("+1ч", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_FROM}:PT1H"),
                ],
                # TODO: get custom time without extra prompt
                # [
                #     InlineKeyboardButton(
                #         "ввести вручную", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_FROM}:custom"
                #     )
                # ],
            ]
        )
        message = "выбери start (по умолчанию сейчас):"
        await self._respond_to_input(user_input, message, kb)

    async def custom_from(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            context.chat_data["start_from"] = str_to_dt(update.message.text, self._bot_manager.bot_config.timezone)
        except Exception as e:
            await update.message.reply_text(f"❌ {e}\nпопробуй ещё раз", reply_markup=MAIN_MENU_KB)
            return
        await self.pick_to(update, context)

    async def pick_to(self, user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.START_PICK_TO)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("+2ч", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_TO}:PT2H"),
                    InlineKeyboardButton("+4ч", callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_TO}:PT4H"),
                ],
                # TODO: get custom time without extra prompt
                # [InlineKeyboardButton("ввести вручную", callback_data=f"{FlowCategory.START}:to:custom")],
            ]
        )
        message = "выбери end (по умолчанию +2ч от start):"
        await self._respond_to_input(user_input, message, kb)

    async def custom_to(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            context.chat_data["start_to"] = str_to_dt(update.message.text, self._bot_manager.bot_config.timezone)
        except Exception as e:
            await update.message.reply_text(f"❌ {e}\nпопробуй ещё раз", reply_markup=MAIN_MENU_KB)
            return
        await self.pick_mode(update, context)

    async def pick_mode(self, user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.START_PICK_MODE)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔎 Искать слоты",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_MODE}:{Mode.ONLY_FIND}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ Записаться",
                        callback_data=f"{FlowCategory.START}:{StartFlowAction.PICK_MODE}:{Mode.FIND_AND_BOOK}",
                    )
                ],
            ]
        )
        message = "выбери режим:"
        await self._respond_to_input(user_input, message, kb)

    async def confirm(self, user_input: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.START_CONFIRM)
        chat_id = user_input.message.chat_id

        pid = context.chat_data["start_project_id"]
        name = context.chat_data["start_project_name"]
        n = int(context.chat_data["start_required_reviews"])
        frm = context.chat_data["start_from"]
        to = context.chat_data["start_to"]
        dry = bool(context.chat_data["start_dry_run"])

        summary = (
            f"проект: {name} (id {pid})\n"
            f"нужно проверок: {n}\n"
            f"окно: {dt_to_pretty(frm)} → {dt_to_pretty(to)}\n"
            f"режим: {'dry-run' if dry else 'booking'}\n\n"
            f"активных: {self._bot_manager.running_count(chat_id)} / max {self._bot_manager.bot_config.max_bots}"
        )
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🚀 старт", callback_data=f"{FlowCategory.START}:{StartFlowAction.CONFIRM}")],
            ]
        )
        await self._respond_to_input(user_input, summary, kb)

    # TODO: figure out the q type (assert message / pass message?)
    async def finalize(self, q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = q.message.chat_id
        if self._bot_manager.running_count(chat_id) >= self._bot_manager.bot_config.max_bots:
            await q.message.reply_text(
                f"Максимальное количество ботов превышено ({self._bot_manager.bot_config.max_bots}) - останови/удали имеющихся или поменяй количество ",
                reply_markup=MAIN_MENU_KB,
            )
            return

        pid = context.chat_data["start_project_id"]
        name = context.chat_data["start_project_name"]
        n = int(context.chat_data["start_required_reviews"])
        frm = context.chat_data["start_from"]
        to = context.chat_data["start_to"]
        dry = bool(context.chat_data["start_dry_run"])

        bot_id = secrets.token_hex(3)
        cfg = BotConfig(
            bot_id=bot_id,
            chat_id=chat_id,
            project_id=pid,
            project_name=name,
            required_reviews=n,
            from_dt=frm,
            to_dt=to,
            interval_sec=self._bot_manager.bot_config.poll_interval_sec,
            dry_run=dry,
        )

        inst = BotInstance(cfg=cfg)
        await q.message.reply_text(f"✅ Запускаю бота #{bot_id}", reply_markup=MAIN_MENU_KB)
        await self._bot_manager.start_bot(inst, context.application)

        # TODO: check if it works without setting menu screen
        # self._screen_set(context, Screen.MENU)
