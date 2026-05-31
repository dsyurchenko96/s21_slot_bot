import enum

import pydantic
from pydantic import TypeAdapter
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from s21_slot_bot.app.consts import MAX_INTERVAL_SEC, MAX_REQUIRED_REVIEWS, MIN_INTERVAL_SEC, MIN_REQUIRED_REVIEWS
from s21_slot_bot.app.flows.base import Flow, FlowAction
from s21_slot_bot.app.models import CustomContext, FlowCategory, IntervalSec, Lifecycle, Mode, RequiredReviews, Screen
from s21_slot_bot.common.exceptions import Error, InternalError, InvalidCallbackDataError, InvalidUserInputError
from s21_slot_bot.common.logger import get_user_input_logger
from s21_slot_bot.common.time import dt_to_pretty, str_to_dt, str_to_dt_with_from


class EditFlowAction(FlowAction):
    PICK_BOT = enum.auto()
    SET_FROM = enum.auto()
    SET_TO = enum.auto()
    SET_INTERVAL = enum.auto()
    PICK_MODE = enum.auto()
    SET_MODE = enum.auto()
    PICK_NUM_REVIEWS = enum.auto()
    SET_NUM_REVIEWS = enum.auto()
    RESTART = enum.auto()


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
                context.chat_data.screen = Screen.EDIT_WAIT_FROM
                await self._messenger.render_menu_message(context, "введи новое начальное время поиска:")
            case EditFlowAction.SET_TO:
                context.chat_data.screen = Screen.EDIT_WAIT_TO
                await self._messenger.render_menu_message(context, "введи новое конечное время поиска:")
            case EditFlowAction.SET_INTERVAL:
                context.chat_data.screen = Screen.EDIT_WAIT_INTERVAL
                await self._messenger.render_menu_message(context, "введи новый интервал (в секундах):")
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
                raise InvalidCallbackDataError

    async def list_bots(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Listing bots...")
        bots = self._bot_manager.list_all()
        if not bots:
            await self._messenger.render_menu_message(context, "нет ботов для изменения")
            return
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"✏️ #{b.cfg.bot_id} — {b.cfg.project_name} ({b.state.to_text()})",
                        callback_data=f"{self._category}:{EditFlowAction.PICK_BOT}:{b.cfg.bot_id}",
                    )
                ]
                for b in bots[:20]
            ]
        )
        await self._messenger.render_menu_message(context, "выбери бота:", kb=kb)

    async def edit_menu(
        self, user_input: Update | CallbackQuery, context: CustomContext, update_text: str = ""
    ) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing edit menu...")
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        c = inst.cfg
        update_text = update_text + "\n" if update_text else ""
        text = update_text + (
            f"✏️ бот #{c.bot_id}\n{c.project_name}\n"
            f"окно: {dt_to_pretty(c.from_dt)} → {dt_to_pretty(c.to_dt)}\n"
            f"интервал: {c.interval_sec} секунд\n"
            f"режим: {c.mode.to_text()}\n"
            f"количество проверок: {c.required_reviews}\n"
            f"статус: {inst.state.to_text()}"
        )
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("начальное время", callback_data=f"{self._category}:{EditFlowAction.SET_FROM}")],
                [InlineKeyboardButton("конечное время", callback_data=f"{self._category}:{EditFlowAction.SET_TO}")],
                [InlineKeyboardButton("интервал", callback_data=f"{self._category}:{EditFlowAction.SET_INTERVAL}")],
                [InlineKeyboardButton("режим", callback_data=f"{self._category}:{EditFlowAction.PICK_MODE}")],
                [
                    InlineKeyboardButton(
                        "количество проверок",
                        callback_data=f"{self._category}:{EditFlowAction.PICK_NUM_REVIEWS}",
                    )
                ],
                [
                    InlineKeyboardButton("перезапустить", callback_data=f"{self._category}:{EditFlowAction.RESTART}"),
                ],
            ]
        )
        await self._messenger.render_menu_message(context, text, kb=kb)

    async def edit_custom_from(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Editing custom search start time...")
        bot_id = context.chat_data.edit_bot_id
        try:
            inst = self._bot_manager.get_bot(bot_id)
            from_dt = str_to_dt(update.message.text, context.bot.defaults.tzinfo, inst.logger())
            if from_dt >= inst.cfg.to_dt:
                raise InvalidUserInputError(
                    f"начальное время должно быть раньше конечного ({dt_to_pretty(inst.cfg.to_dt)})"
                )
        except Error:
            # TODO: check necessity of explicit call
            await self.edit_menu(update, context)
            raise
        inst.cfg.from_dt = from_dt
        await self.edit_menu(update, context, update_text="✅ начальное время обновлено")

    async def edit_custom_to(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Editing custom search end time...")
        bot_id = context.chat_data.edit_bot_id
        try:
            inst = self._bot_manager.get_bot(bot_id)
            from_dt = inst.cfg.from_dt
            if not from_dt:
                raise InternalError("начальное время поиска не задано", location=context.chat_data.model_dump())
            to_dt = str_to_dt_with_from(update.message.text, context.bot.defaults.tzinfo, from_dt, inst.logger())
            if to_dt >= inst.cfg.from_dt:
                raise InvalidUserInputError(
                    f"конечное время должно быть позже начального ({dt_to_pretty(inst.cfg.from_dt)})"
                )
        except Error:
            await self.edit_menu(update, context)
            raise
        inst.cfg.to_dt = to_dt
        await self.edit_menu(update, context, update_text="✅ конечное время обновлено")

    async def edit_custom_interval(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Editing interval...")
        bot_id = context.chat_data.edit_bot_id
        try:
            inst = self._bot_manager.get_bot(bot_id)
            interval_sec = TypeAdapter(IntervalSec).validate_strings(update.message.text)
        except pydantic.ValidationError as e:
            await self.edit_menu(update, context)
            raise InvalidUserInputError(
                f"интервал может быть задан только от {MIN_INTERVAL_SEC} до {MAX_INTERVAL_SEC} секунд"
            ) from e
        except Error:
            await self.edit_menu(update, context)
            raise
        inst.cfg.interval_sec = interval_sec
        await self.edit_menu(update, context, update_text="✅ интервал обновлен")

    async def pick_mode(self, query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        logger.info("Editing bot search mode...")
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔎 Искать слоты",
                        callback_data=f"{self._category}:{EditFlowAction.SET_MODE}:{Mode.ONLY_FIND}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ Записаться",
                        callback_data=f"{self._category}:{EditFlowAction.SET_MODE}:{Mode.FIND_AND_BOOK}",
                    )
                ],
            ]
        )
        await self._messenger.render_menu_message(context, "выбери режим:", kb=kb)

    async def pick_num_reviews(self, query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        logger.info("Editing bot review number...")
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        str(num), callback_data=f"{self._category}:{EditFlowAction.SET_NUM_REVIEWS}:{num}"
                    )
                    for num in range(MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS + 1)
                ],
            ]
        )
        await self._messenger.render_menu_message(context, "сколько проверок нужно (1–3)?", kb=kb)

    async def edit_restart(self, query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        bot_id = context.chat_data.edit_bot_id
        logger.info("Restarting bot `%s`...", bot_id)
        try:
            inst = self._bot_manager.get_bot(bot_id)
            if inst.state == Lifecycle.RUNNING:
                raise InvalidUserInputError(f"бот #{bot_id} уже активен", help_text="выбери другого бота")
            self._bot_manager.check_bot_limits()
        except Error:
            await self.edit_menu(query, context)
            raise

        await self._bot_manager.start_bot(inst, context)
        await self.edit_menu(query, context, update_text=f"🔄 Бот #{bot_id} перезапущен")
