import enum
from enum import StrEnum

from telegram import CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from s21_slot_bot.app.exceptions import InvalidCallbackData
from s21_slot_bot.app.flows.base import Flow
from s21_slot_bot.app.menu_markup import MAIN_MENU_KB
from s21_slot_bot.app.models import Screen


class SettingsFlowAction(StrEnum):
    PICK_MAX = enum.auto()
    SET_MAX = enum.auto()
    INTERVAL = enum.auto()


class SettingsFlow(Flow):
    async def parse_callback(
        self, callback_data: list[str], query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        action = callback_data.pop()
        match action:
            case SettingsFlowAction.PICK_MAX:
                await self.settings_pick_max(query, context)
            case SettingsFlowAction.SET_MAX:
                new_max = int(callback_data.pop())
                await self.settings_apply_max(query, context, new_max)
            case SettingsFlowAction.INTERVAL:
                self._screen_set(context, Screen.SETTINGS_WAIT_INTERVAL)
                await query.message.reply_text("введи новый глобальный интервал (сек)", reply_markup=MAIN_MENU_KB)
            case _:
                raise InvalidCallbackData

    async def settings_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._screen_set(context, Screen.SETTINGS_MENU)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"макс. ботов: {self._bot_manager.config.max_bots}", callback_data="settings:max"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"интервал: {self._bot_manager.config.poll_interval_sec}s", callback_data="settings:interval"
                    )
                ],
            ]
        )
        await update.message.reply_text("⚙️ настройки:", reply_markup=kb)

    async def settings_pick_max(self, q, context: ContextTypes.DEFAULT_TYPE) -> None:
        kb = [[InlineKeyboardButton(str(n), callback_data=f"settings:setmax:{n}")] for n in range(1, 6)]
        await q.message.reply_text("выбери max bots (1–5):", reply_markup=InlineKeyboardMarkup(kb))

    async def settings_apply_max(self, q, context: ContextTypes.DEFAULT_TYPE, new_max: int) -> None:
        chat_id = q.message.chat_id
        old = self._bot_manager.config.max_bots
        self._bot_manager.config.max_bots = max(1, new_max)

        # если уменьшили ниже текущего running — останавливаем "лишние" (последние)
        if self._bot_manager.running_count(chat_id) > self._bot_manager.config.max_bots:
            extras = self._bot_manager.running_count(chat_id) - self._bot_manager.config.max_bots
            for inst in self._bot_manager.running(chat_id)[-extras:]:
                self._bot_manager.stop_bot(inst.cfg.bot_id)

        await q.message.reply_text(
            f"✅ max bots: {old} → {self._bot_manager.config.max_bots}", reply_markup=MAIN_MENU_KB
        )
        await self._bot_manager.try_start_next(chat_id, context.application)

    async def settings_custom_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            val = int((update.message.text or "").strip())
            if val < 10 or val > 3600:
                raise ValueError("интервал 10..3600")
            self._bot_manager.config.poll_interval_sec = val
        except Exception as e:
            await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_MENU_KB)
            return
        self._screen_set(context, Screen.SETTINGS_MENU)
        await update.message.reply_text(f"✅ интервал: {val}s", reply_markup=MAIN_MENU_KB)
