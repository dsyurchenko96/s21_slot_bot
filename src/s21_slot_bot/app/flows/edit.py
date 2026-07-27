from datetime import datetime
from typing import Any, Callable, Coroutine, cast, override

import pydantic
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from s21_slot_bot.app.consts import MAX_INTERVAL_SEC, MIN_INTERVAL_SEC
from s21_slot_bot.app.errors import InternalError, InvalidCallbackDataError, InvalidUserInputError
from s21_slot_bot.app.flows.actions import EditFlowAction, FlowAction, InputFlowAction
from s21_slot_bot.app.flows.base import CustomInputFlow
from s21_slot_bot.app.models import (
    CustomContext,
    IntervalSecAdapter,
    Lifecycle,
    Mode,
    RequiredReviewsAdapter,
    Screen,
)
from s21_slot_bot.client.consts import MIN_REQUIRED_REVIEWS
from s21_slot_bot.common.logger import LoggerLike, get_user_input_logger
from s21_slot_bot.common.strings import escape_str
from s21_slot_bot.common.time import dt_to_pretty, parse_to_datetime


class EditFlow(CustomInputFlow):
    @property
    def _action_to_method(
        self,
    ) -> dict[FlowAction, Callable[[Update | CallbackQuery, CustomContext], Coroutine[Any, Any, None]]]:
        return {
            EditFlowAction.LIST_BOTS: self.list_bots,
            EditFlowAction.SHOW_MENU: self.edit_menu,
        }

    @override
    @property
    def _action_to_screen(self) -> dict[FlowAction, Screen]:
        return {
            InputFlowAction.PICK_FROM: Screen.EDIT_WAIT_FROM,
            InputFlowAction.PICK_TO: Screen.EDIT_WAIT_TO,
            EditFlowAction.SET_INTERVAL: Screen.EDIT_WAIT_INTERVAL,
        }

    @override
    def _get_prev_action(self, action: FlowAction, context: CustomContext) -> FlowAction | None:
        match action:
            case EditFlowAction.SHOW_MENU:
                return EditFlowAction.LIST_BOTS
            case _:
                return EditFlowAction.SHOW_MENU

    @override
    def _get_chosen_project_info_text(
        self, context: CustomContext, action: FlowAction | None = None, is_markdown: bool = False
    ) -> str:
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        c = inst.cfg
        project_name = escape_str(c.project_name) if is_markdown else c.project_name
        from_pretty = dt_to_pretty(c.from_dt, tz=context.bot.defaults.tzinfo)
        to_pretty = dt_to_pretty(c.to_dt, tz=context.bot.defaults.tzinfo)
        text = (
            f"✏️ бот #{c.bot_id} ({project_name})\n"
            f"окно: {from_pretty} → {to_pretty}\n"
            f"интервал: {c.interval_sec} секунд\n"
            f"режим: {c.mode.to_text()}\n"
            f"количество проверок: {c.required_reviews}\n"
            f"статус: {inst.state.to_text()}\n\n"
        )
        return text

    @override
    async def parse_callback(self, callback_data: list[str], query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        action = callback_data.pop()
        match action:
            case EditFlowAction.PICK_BOT:
                bot_id = callback_data.pop()
                context.chat_data.edit_bot_id = bot_id
                await self.edit_menu(query, context)
            case EditFlowAction.MENU_FROM:
                await self.pick_from(query, context)
            case InputFlowAction.PICK_FROM:
                self._set_from(callback_data.pop(), context, logger)
                await self.edit_menu(query, context, update_text="✅ начальное время обновлено")
                # context.chat_data.screen = Screen.EDIT_WAIT_FROM
                # await self._messenger.render_menu_message(context, "введи новое начальное время поиска:")
            case EditFlowAction.MENU_TO:
                await self.pick_to(query, context)
                # context.chat_data.screen = Screen.EDIT_WAIT_TO
                # await self._messenger.render_menu_message(context, "введи новое конечное время поиска:")
            case InputFlowAction.PICK_TO:
                self._set_to(callback_data.pop(), context, logger)
                await self.edit_menu(query, context, update_text="✅ конечное время обновлено")
            case EditFlowAction.MENU_MODE:
                await self.pick_mode(query, context)
            case InputFlowAction.PICK_MODE:
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
                        await self.edit_menu(query, context, update_text="✅ режим обновлен")
                    case Mode.FIND_AND_BOOK:
                        await self.pick_num_reviews(query, context)
            case EditFlowAction.MENU_NUM_REVIEWS:
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
            case InputFlowAction.PICK_NUM_REVIEWS:
                num_reviews = RequiredReviewsAdapter.validate_strings(callback_data.pop())
                bot_id = context.chat_data.edit_bot_id
                inst = self._bot_manager.get_bot(bot_id)
                update_text = "✅ количество проверок обновлено" if inst.cfg.required_reviews != num_reviews else ""
                inst.cfg.required_reviews = num_reviews
                await self.edit_menu(query, context, update_text=update_text)
            case EditFlowAction.PICK_INTERVAL:
                await self.edit_interval(query, context)
            case EditFlowAction.SET_INTERVAL:
                interval = IntervalSecAdapter.validate_strings(callback_data.pop())
                bot_id = context.chat_data.edit_bot_id
                inst = self._bot_manager.get_bot(bot_id)
                update_text = ""
                if inst.cfg.interval_sec != interval:
                    self._bot_manager.stop_bot(bot_id, context, logger)
                    inst.cfg.interval_sec = interval
                    await self._bot_manager.start_bot(inst, context, logger)
                    update_text = "✅ интервал обновлен, бот перезапущен"
                await self.edit_menu(query, context, update_text=update_text)
                # context.chat_data.screen = Screen.EDIT_WAIT_INTERVAL
                # text = self._get_chosen_project_info_text(context) + "введи новый интервал (в секундах):"
                # await self._messenger.render_menu_message(context, text)
            case EditFlowAction.RESTART:
                await self.edit_restart(query, context)
            case InputFlowAction.BACK:
                prev_action = cast(FlowAction, callback_data.pop())
                prev_method = self._action_to_method.get(prev_action)
                if not prev_method:
                    raise InvalidCallbackDataError("предыдущее действие не задано")
                await prev_method(query, context)
            case _:
                raise InvalidCallbackDataError(f"неподдерживаемое действие '{action}' при редактировании бота")

    async def list_bots(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Listing bots...")
        bots = self._bot_manager.list_all()
        if not bots:
            await self._messenger.render_menu_message(context, "🚫 нет ботов", logger)
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
        await self._messenger.render_menu_message(context, "выбери бота:", logger, kb=kb)

    async def edit_menu(
        self, user_input: Update | CallbackQuery, context: CustomContext, update_text: str = ""
    ) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Showing edit menu...")
        action = EditFlowAction.SHOW_MENU
        prev_action = self._get_prev_action(action, context)
        self._set_screen(action, context)
        buttons = [
            [InlineKeyboardButton("начальное время", callback_data=f"{self._category}:{EditFlowAction.MENU_FROM}")],
            [InlineKeyboardButton("конечное время", callback_data=f"{self._category}:{EditFlowAction.MENU_TO}")],
            [InlineKeyboardButton("режим", callback_data=f"{self._category}:{EditFlowAction.MENU_MODE}")],
            [
                InlineKeyboardButton(
                    "количество проверок",
                    callback_data=f"{self._category}:{EditFlowAction.MENU_NUM_REVIEWS}",
                )
            ],
            [InlineKeyboardButton("интервал", callback_data=f"{self._category}:{EditFlowAction.PICK_INTERVAL}")],
            [
                InlineKeyboardButton("перезапустить", callback_data=f"{self._category}:{EditFlowAction.RESTART}"),
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
        text = self._get_chosen_project_info_text(context, is_markdown=True) + update_text
        await self._messenger.render_menu_message(context, text, logger, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    def _set_from(self, text: str, context: CustomContext, logger: LoggerLike) -> None:
        logger.info("Editing custom search start time...")
        now = datetime.now(tz=context.bot.defaults.tzinfo)
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        from_dt = parse_to_datetime(text, context.bot.defaults.tzinfo, now, logger)
        if from_dt >= inst.cfg.to_dt:
            raise InvalidUserInputError(
                f"начальное время должно быть раньше конечного ({dt_to_pretty(inst.cfg.to_dt, tz=context.bot.defaults.tzinfo)})"
            )
        inst.cfg.from_dt = from_dt

    async def edit_custom_from(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        # try:
        self._set_from(update.message.text, context, logger)
        # except Error:
        #     await self.pick_from(update, context)
        #     raise
        await self.edit_menu(update, context, update_text="✅ начальное время обновлено")

    def _set_to(self, text: str, context: CustomContext, logger: LoggerLike) -> None:
        logger.info("Editing custom search start time...")
        bot_id = context.chat_data.edit_bot_id
        inst = self._bot_manager.get_bot(bot_id)
        from_dt = inst.cfg.from_dt
        if not from_dt:
            raise InternalError("начальное время поиска не задано", location=context.chat_data.model_dump())
        to_dt = parse_to_datetime(text, context.bot.defaults.tzinfo, from_dt, logger)
        if to_dt <= inst.cfg.from_dt:
            raise InvalidUserInputError(
                f"конечное время должно быть позже начального ({dt_to_pretty(inst.cfg.from_dt, tz=context.bot.defaults.tzinfo)})"
            )
        inst.cfg.to_dt = to_dt

    async def edit_custom_to(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        # try:
        self._set_to(update.message.text, context, logger)
        # except Error:
        #     await self.pick_to(update, context)
        #     raise
        await self.edit_menu(update, context, update_text="✅ конечное время обновлено")

    async def edit_interval(
        self,
        user_input: CallbackQuery | Update,
        context: CustomContext,
    ) -> None:
        logger = get_user_input_logger(user_input)
        logger.info("Editing interval...")
        action = EditFlowAction.SET_INTERVAL
        prev_action = self._get_prev_action(action, context)
        self._set_screen(action, context)
        buttons = [
            [
                InlineKeyboardButton(f"{seconds}с", callback_data=f"{self._category}:{action}:{seconds}")
                for seconds in [10, 20, 30, 60, 120]
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
            + "выбери или введи новый интервал (в секундах):"
        )
        await self._messenger.render_menu_message(context, text, logger, kb=kb, parse_mode=ParseMode.MARKDOWN_V2)

    async def edit_custom_interval(self, update: Update, context: CustomContext) -> None:
        logger = get_user_input_logger(update)
        logger.info("Editing custom interval...")
        bot_id = context.chat_data.edit_bot_id
        try:
            inst = self._bot_manager.get_bot(bot_id)
            interval_sec = IntervalSecAdapter.validate_strings(update.message.text)
        except pydantic.ValidationError as e:
            # await self.edit_interval(update, context)
            raise InvalidUserInputError(
                f"интервал может быть задан только от {MIN_INTERVAL_SEC} до {MAX_INTERVAL_SEC} секунд"
            ) from e
        # except Error:
        #     await self.edit_interval(update, context)
        #     raise
        inst.cfg.interval_sec = interval_sec
        self._bot_manager.stop_bot(bot_id, context, logger)
        await self._bot_manager.start_bot(inst, context, logger)
        await self.edit_menu(update, context, update_text="✅ интервал обновлен, бот перезапущен")

    # async def pick_mode(self, query: CallbackQuery, context: CustomContext) -> None:
    #     logger = get_user_input_logger(query)
    #     logger.info("Editing bot search mode...")
    #     kb = InlineKeyboardMarkup(
    #         [
    #             [
    #                 InlineKeyboardButton(
    #                     "🔎 Искать слоты",
    #                     callback_data=f"{self._category}:{EditFlowAction.SET_MODE}:{Mode.ONLY_FIND}",
    #                 )
    #             ],
    #             [
    #                 InlineKeyboardButton(
    #                     "✅ Записаться",
    #                     callback_data=f"{self._category}:{EditFlowAction.SET_MODE}:{Mode.FIND_AND_BOOK}",
    #                 )
    #             ],
    #         ]
    #     )
    #     await self._messenger.render_menu_message(context, "выбери режим:", kb=kb)

    # async def pick_num_reviews(self, query: CallbackQuery, context: CustomContext) -> None:
    #     logger = get_user_input_logger(query)
    #     logger.info("Editing bot review number...")
    #     kb = InlineKeyboardMarkup(
    #         [
    #             [
    #                 InlineKeyboardButton(
    #                     str(num), callback_data=f"{self._category}:{EditFlowAction.SET_NUM_REVIEWS}:{num}"
    #                 )
    #                 for num in range(MIN_REQUIRED_REVIEWS, MAX_REQUIRED_REVIEWS + 1)
    #             ],
    #         ]
    #     )
    #     await self._messenger.render_menu_message(context, "сколько проверок нужно (1–3)?", kb=kb)

    async def edit_restart(self, query: CallbackQuery, context: CustomContext) -> None:
        logger = get_user_input_logger(query)
        bot_id = context.chat_data.edit_bot_id
        logger.info("Restarting bot `%s`...", bot_id)
        action = EditFlowAction.RESTART
        self._set_screen(action, context)
        inst = self._bot_manager.get_bot(bot_id)
        if inst.state == Lifecycle.RUNNING:
            raise InvalidUserInputError(f"бот #{bot_id} уже активен", help_text="выбери другого бота")
        self._bot_manager.check_bot_limits()

        await self._bot_manager.start_bot(inst, context, logger)
        await self.edit_menu(query, context, update_text=f"🔄 бот #{bot_id} перезапущен")
