import enum
from enum import StrEnum
from functools import wraps
from typing import Awaitable, Callable

from pydantic import TypeAdapter
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.consts import MAX_INTERVAL_SEC, MAX_REQUIRED_REVIEWS, MIN_INTERVAL_SEC, MIN_REQUIRED_REVIEWS
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.messages import render_message
from s21_slot_bot.app.models import CustomContext, FlowCategory, Lifecycle, Mode, Screen
from s21_slot_bot.app.types import IntervalSec, RequiredReviews
from s21_slot_bot.common.exceptions import BotNotFound, InvalidCallbackData, InvalidUserInput
from s21_slot_bot.common.time import dt_to_pretty, str_to_dt


class EditFlowAction(StrEnum):
    PICK_BOT = enum.auto()
    SET_FROM = enum.auto()
    SET_TO = enum.auto()
    SET_INTERVAL = enum.auto()
    PICK_MODE = enum.auto()
    SET_MODE = enum.auto()
    PICK_NUM_REVIEWS = enum.auto()
    SET_NUM_REVIEWS = enum.auto()
    RESTART = enum.auto()


def edit_input_wrapper(
    edit_method: Callable[[EditFlow, Update, CustomContext], str],
) -> Callable[[EditFlow, Update, CustomContext], Awaitable[None]]:
    @wraps(edit_method)
    async def wrapper(self: EditFlow, update: Update, context: CustomContext) -> None:
        try:
            menu_update_text = edit_method(self, update, context)
        except BotNotFound as e:
            menu_update_text = f"❌ {e}"
        except InvalidUserInput as e:
            await render_message(update, context, f"❌ {e}\nпопробуй ещё раз")
            return
        await self.edit_menu(update, context, update_text=menu_update_text)

    return wrapper


class EditFlow(Flow):
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        action = callback_data.pop()
        match action:
            case EditFlowAction.PICK_BOT:
                bot_id = callback_data.pop()
                # TODO: pass as argument in all edit callbacks?
                context.chat_data.edit_bot_id = bot_id
                await self.edit_menu(query, context)
            case EditFlowAction.SET_FROM:
                self._screen_set(context, Screen.EDIT_WAIT_FROM)
                await render_message(query, context, "введи новое начальное время поиска:")
            case EditFlowAction.SET_TO:
                self._screen_set(context, Screen.EDIT_WAIT_TO)
                await render_message(query, context, "введи новое конечное время поиска:")
            case EditFlowAction.SET_INTERVAL:
                self._screen_set(context, Screen.EDIT_WAIT_INTERVAL)
                await render_message(query, context, "введи новый интервал (в секундах):")
            case EditFlowAction.PICK_MODE:
                await self.pick_mode(query, context)
            case EditFlowAction.SET_MODE:
                bot_id = context.chat_data.edit_bot_id
                inst = self._bot_manager.get_bot(bot_id)
                mode = Mode(callback_data.pop())
                if mode == inst.cfg.mode:
                    await self.edit_menu(query, context)
                    return
                inst.cfg.mode = mode
                match mode:
                    case Mode.ONLY_FIND:
                        inst.cfg.required_reviews = MIN_REQUIRED_REVIEWS
                        await self.edit_menu(query, context)
                    case Mode.FIND_AND_BOOK:
                        await self.pick_num_reviews(query, context)
            case EditFlowAction.PICK_NUM_REVIEWS:
                bot_id = context.chat_data.edit_bot_id
                inst = self._bot_manager.get_bot(bot_id)
                match inst.cfg.mode:
                    case Mode.ONLY_FIND:
                        menu_update_text = (
                            f"поменять количество проверок можно только в режиме `{Mode.FIND_AND_BOOK.to_text()}`"
                        )
                        await self.edit_menu(query, context, update_text=menu_update_text)
                    case Mode.FIND_AND_BOOK:
                        await self.pick_num_reviews(query, context)
            case EditFlowAction.SET_NUM_REVIEWS:
                num_reviews = TypeAdapter(RequiredReviews).validate_strings(callback_data.pop())
                bot_id = context.chat_data.edit_bot_id
                inst = self._bot_manager.get_bot(bot_id)
                inst.cfg.required_reviews = num_reviews
                await self.edit_menu(query, context)
            case EditFlowAction.RESTART:
                await self.edit_restart(query, context)
            case _:
                raise InvalidCallbackData

    # TODO: change signature
    async def list_bots(self, update: Update, context: CustomContext) -> None:
        self._screen_set(context, Screen.EDIT_PICK)
        chat_id = update.message.chat_id
        bots = self._bot_manager.list_all(chat_id)
        if not bots:
            text = "нет ботов для изменения"
            await render_message(update, context, text)
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"✏️ #{b.cfg.bot_id} — {b.cfg.project_name} ({b.state.to_text()})",
                        callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.PICK_BOT}:{b.cfg.bot_id}",
                    )
                ]
                for b in bots[:20]
            ]
        )
        text = "выбери бота:"
        await render_message(update, context, text, kb=kb)

    async def edit_menu(self, q, context: CustomContext, update_text: str = "") -> None:
        self._screen_set(context, Screen.EDIT_MENU)
        bot_id = context.chat_data.edit_bot_id
        try:
            inst = self._bot_manager.get_bot(bot_id)
        except BotNotFound as e:
            await render_message(q, context, f"❌ {e}")
            return
        c = inst.cfg
        update_text = update_text + "\n" if update_text else ""
        text = update_text + (
            f"✏️ бот #{c.bot_id}\n{c.project_name}\n"
            f"окно: {dt_to_pretty(c.from_dt)} → {dt_to_pretty(c.to_dt)}\n"
            f"интервал: {c.interval_sec} секунд\n"
            f"режим: {c.mode.to_text()}\n"
            f"статус: {inst.state.to_text()}"
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "начальное время", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_FROM}"
                    ),
                    InlineKeyboardButton(
                        "конечное время", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_TO}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "интервал", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_INTERVAL}"
                    ),
                    InlineKeyboardButton("режим", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.PICK_MODE}"),
                    InlineKeyboardButton(
                        "количество проверок", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.PICK_NUM_REVIEWS}"
                    ),
                ],
                [InlineKeyboardButton("перезапустить", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.RESTART}")],
            ]
        )
        await render_message(q, context, text, kb=kb)

    @edit_input_wrapper
    def edit_custom_from(self, update: Update, context: CustomContext) -> str:
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        from_dt = str_to_dt(update.message.text, self._bot_manager.bot_config.timezone, inst.logger())
        if from_dt >= inst.cfg.to_dt:
            raise InvalidUserInput(f"начальное время должно быть раньше конечного ({dt_to_pretty(inst.cfg.to_dt)})")
        inst.cfg.from_dt = from_dt
        menu_update_text = "✅ начальное время обновлено"
        return menu_update_text

    @edit_input_wrapper
    def edit_custom_to(self, update: Update, context: CustomContext) -> str:
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        to_dt = str_to_dt(update.message.text, self._bot_manager.bot_config.timezone, inst.logger())
        if to_dt >= inst.cfg.from_dt:
            raise InvalidUserInput(f"конечное время должно быть позже начального ({dt_to_pretty(inst.cfg.from_dt)})")
        inst.cfg.to_dt = to_dt
        menu_update_text = "✅ конечное время обновлено"
        return menu_update_text

    @edit_input_wrapper
    async def edit_custom_interval(self, update: Update, context: CustomContext) -> str:
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        try:
            interval_sec = TypeAdapter(IntervalSec).validate_strings(update.message.text)
        except ValueError as e:
            raise InvalidUserInput(
                f"интервал может быть задан только от {MIN_INTERVAL_SEC} до {MAX_INTERVAL_SEC} секунд"
            ) from e
        inst.cfg.interval_sec = interval_sec
        menu_update_text = "✅ интервал обновлен"
        return menu_update_text

    async def pick_mode(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔎 Искать слоты",
                        callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_MODE}:{Mode.ONLY_FIND}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ Записаться",
                        callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_MODE}:{Mode.FIND_AND_BOOK}",
                    )
                ],
            ]
        )
        text = "выбери режим:"
        await render_message(user_input, context, text, kb=kb)

    async def pick_num_reviews(self, user_input: Update | CallbackQuery, context: CustomContext) -> None:
        # self._screen_set(context, Screen.ED)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        str(num), callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_NUM_REVIEWS}:{num}"
                    )
                    for num in range(MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS + 1)
                ],
            ]
        )
        text = "сколько проверок нужно (1–3)?"
        await render_message(user_input, context, text, kb=kb)
        # await self._respond_to_input(user_input, message, kb)

    async def edit_restart(self, q, context: CustomContext) -> None:
        chat_id = q.message.chat_id
        bot_id = context.chat_data.edit_bot_id
        try:
            inst = self._bot_manager.get_bot(bot_id)
            if inst.state == Lifecycle.RUNNING:
                raise InvalidUserInput(f"бот #{bot_id} уже активен")
            if self._bot_manager.running_count(chat_id) >= self._bot_manager.bot_config.max_bots:
                raise InvalidUserInput(
                    f"Максимальное количество ботов превышено ({self._bot_manager.bot_config.max_bots}) - останови/удали имеющихся или поменяй максимальное количество"
                )
        except (BotNotFound, InvalidUserInput) as e:
            await self.edit_menu(q, context, update_text=f"❌ {e}")
            return

        self._bot_manager.start_bot(inst, context.application)
        await self.edit_menu(q, context, update_text=f"🔄 Бот #{bot_id} перезапущен")
