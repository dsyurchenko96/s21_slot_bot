import enum
from enum import StrEnum

from telegram import CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import Screen, Lifecycle, FlowCategory
from s21_slot_bot.common.time import str_to_dt


class EditFlowAction(StrEnum):
    PICK_BOT = enum.auto()
    SET_FROM = enum.auto()
    SET_TO = enum.auto()
    SET_INTERVAL = enum.auto()
    TOGGLE_DRY = enum.auto()
    RESTART = enum.auto()


class EditFlow(Flow):
    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        action = callback_data.pop()
        match action:
            case EditFlowAction.PICK_BOT:
                bot_id = callback_data.pop()
                # TODO: pass as argument in all edit callbacks?
                context.chat_data["edit_bot_id"] = bot_id
                await self.edit_menu(query, context)
            case EditFlowAction.SET_FROM:
                self._screen_set(context, Screen.EDIT_WAIT_FROM)
                await query.message.reply_text("введи новый start", reply_markup=MAIN_MENU_KB)
            case EditFlowAction.SET_TO:
                self._screen_set(context, Screen.EDIT_WAIT_TO)
                await query.message.reply_text("введи новый end", reply_markup=MAIN_MENU_KB)
            case EditFlowAction.SET_INTERVAL:
                self._screen_set(context, Screen.EDIT_WAIT_INTERVAL)
                await query.message.reply_text("введи новый интервал (сек)", reply_markup=MAIN_MENU_KB)
            case EditFlowAction.TOGGLE_DRY:
                bot_id = context.chat_data.get("edit_bot_id")
                inst = self._bot_manager.get_bot(bot_id)
                if inst:
                    inst.cfg.dry_run = not inst.cfg.dry_run
                await self.edit_menu(query, context)
            case EditFlowAction.RESTART:
                await self.edit_restart(query, context)
            case _:
                raise InvalidCallbackData

    async def edit_pick(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.EDIT_PICK)
        chat_id = update.message.chat_id
        bots = self._bot_manager.running(chat_id)
        if not bots:
            await update.message.reply_text("нет активных ботов для изменения", reply_markup=MAIN_MENU_KB)
            return
        kb = [
            [
                InlineKeyboardButton(
                    f"✏️ #{b.cfg.bot_id} — {b.cfg.project_name}",
                    callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.PICK_BOT}:{b.cfg.bot_id}",
                )
            ]
            for b in bots[:20]
        ]
        await update.message.reply_text("выбери бота:", reply_markup=InlineKeyboardMarkup(kb))

    async def edit_menu(self, q, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.EDIT_MENU)
        bot_id = context.chat_data.get("edit_bot_id")
        inst = self._bot_manager.get_bot(bot_id)
        if not inst:
            await q.message.reply_text(f"не нашёл бота #{bot_id}", reply_markup=MAIN_MENU_KB)
            return
        c = inst.cfg
        text = (
            f"✏️ bot #{c.bot_id}\n{c.project_name}\n"
            f"utc: {c.from_dt} → {c.to_dt}\n"
            f"interval: {c.interval_sec}s\nmode: {'dry-run' if c.dry_run else 'booking'}\n"
            f"state: {inst.state}"
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "изменить start", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_FROM}"
                    ),
                    InlineKeyboardButton("изменить end", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_TO}"),
                ],
                [
                    InlineKeyboardButton(
                        "интервал", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.SET_INTERVAL}"
                    ),
                    InlineKeyboardButton(
                        "toggle dry", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.TOGGLE_DRY}"
                    ),
                ],
                [InlineKeyboardButton("перезапустить", callback_data=f"{FlowCategory.EDIT}:{EditFlowAction.RESTART}")],
            ]
        )
        await q.message.reply_text(text, reply_markup=kb)

    async def edit_custom_from(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot_id = context.chat_data.get("edit_bot_id")
        inst = self._bot_manager.get_bot(bot_id)
        if not inst:
            await update.message.reply_text(f"не нашёл бота #{bot_id}", reply_markup=MAIN_MENU_KB)
            self._screen_set(context, Screen.MENU)
            return
        try:
            inst.cfg.from_dt = str_to_dt(update.message.text, self._bot_manager.bot_config.timezone)
        except Exception as e:
            await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
            return
        self._screen_set(context, Screen.EDIT_MENU)
        await update.message.reply_text("✅ обновил start", reply_markup=MAIN_MENU_KB)

    async def edit_custom_to(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot_id = context.chat_data.get("edit_bot_id")
        inst = self._bot_manager.get_bot(bot_id)
        if not inst:
            await update.message.reply_text(f"не нашёл бота {bot_id}", reply_markup=MAIN_MENU_KB)
            self._screen_set(context, Screen.MENU)
            return
        try:
            inst.cfg.to_dt = str_to_dt(update.message.text, self._bot_manager.bot_config.timezone)
        except Exception as e:
            await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
            return
        self._screen_set(context, Screen.EDIT_MENU)
        await update.message.reply_text("✅ обновил end", reply_markup=MAIN_MENU_KB)

    async def edit_custom_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        bot_id = context.chat_data.get("edit_bot_id")
        inst = self._bot_manager.get_bot(bot_id)
        if not inst:
            await update.message.reply_text(f"не нашёл бота #{bot_id}", reply_markup=MAIN_MENU_KB)
            self._screen_set(context, Screen.MENU)
            return
        try:
            val = int((update.message.text or "").strip())
            if val < 10 or val > 3600:
                raise ValueError("интервал 10..3600")
            inst.cfg.interval_sec = val
        except Exception as e:
            await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
            return
        self._screen_set(context, Screen.EDIT_MENU)
        await update.message.reply_text("✅ обновил интервал", reply_markup=MAIN_MENU_KB)

    async def edit_restart(self, q, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = q.message.chat_id
        bot_id = context.chat_data.get("edit_bot_id")
        inst = self._bot_manager.get_bot(bot_id)
        if not inst:
            await q.message.reply_text(f"не нашёл бота #{bot_id}", reply_markup=MAIN_MENU_KB)
            return
        if inst.state == Lifecycle.RUNNING:
            await q.message.reply_text(f"бот #{bot_id} уже активен", reply_markup=MAIN_MENU_KB)
            return
        if self._bot_manager.running_count(chat_id) >= self._bot_manager.bot_config.max_bots:
            await q.message.reply_text(
                f"Максимальное количество ботов превышено ({self._bot_manager.bot_config.max_bots}) - останови/удали имеющихся или поменяй максимальное количество",
                reply_markup=MAIN_MENU_KB,
            )
            return

        await q.message.reply_text(f"🔄 Перезапускаю бота #{bot_id}", reply_markup=MAIN_MENU_KB)
        await self._bot_manager.start_bot(inst, context.application)
